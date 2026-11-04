import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { useEventListener, useResizeObserver } from '@vueuse/core'

const SMOOTH_SCROLL_TIMEOUT = 900

export function useChatScroll(container: Ref<HTMLElement | null>, content: Ref<HTMLElement | null>) {
  const atBottom = ref(true)
  const showButton = ref(false)
  let smoothScrolling = false
  let smoothTimer: number | null = null
  let smoothEndHandler: (() => void) | null = null

  const clearSmoothWait = () => {
    if (smoothTimer !== null) {
      window.clearTimeout(smoothTimer)
      smoothTimer = null
    }
    if (smoothEndHandler) {
      container.value?.removeEventListener('scrollend', smoothEndHandler)
      smoothEndHandler = null
    }
  }

  const finishSmoothScroll = () => {
    if (!smoothScrolling) return
    smoothScrolling = false
    clearSmoothWait()
    const element = container.value
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    if (distance > 2 && document.visibilityState !== 'hidden') {
      // 滚动期间内容又变高了，继续平滑追到底部
      scrollToBottom('smooth')
      return
    }
    element.scrollTop = element.scrollHeight
    atBottom.value = true
    showButton.value = false
  }

  const cancelSmoothScroll = () => {
    if (!smoothScrolling) return
    smoothScrolling = false
    clearSmoothWait()
    measure()
  }

  const jumpToBottom = () => {
    const element = container.value
    if (!element) return
    element.scrollTop = element.scrollHeight
    atBottom.value = true
    showButton.value = false
  }

  const measure = () => {
    if (smoothScrolling) return
    const element = container.value
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    atBottom.value = distance < 96
    showButton.value = distance > 160
  }

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    const element = container.value
    if (!element) return
    if (behavior !== 'smooth') {
      cancelSmoothScroll()
      jumpToBottom()
      return
    }
    clearSmoothWait()
    smoothScrolling = true
    atBottom.value = false
    showButton.value = false
    element.scrollTo({ top: element.scrollHeight, behavior })
    smoothEndHandler = finishSmoothScroll
    element.addEventListener('scrollend', smoothEndHandler, { once: true })
    smoothTimer = window.setTimeout(finishSmoothScroll, SMOOTH_SCROLL_TIMEOUT)
  }

  useEventListener(container, 'scroll', measure, { passive: true })
  useEventListener(container, 'wheel', cancelSmoothScroll, { passive: true })
  useEventListener(container, 'touchstart', cancelSmoothScroll, { passive: true })
  useEventListener(container, 'pointerdown', cancelSmoothScroll, { passive: true })
  useEventListener(container, 'keydown', cancelSmoothScroll)

  // 贴底时一次读一次写就够；刚写完再 measure 会多付一轮布局。
  // 不在底部时仍要 measure，靠它把「滚动到最新消息」按钮点亮。
  useResizeObserver(content, () => {
    if (smoothScrolling) return
    if (atBottom.value) jumpToBottom()
    else measure()
  })

  onMounted(() => {
    nextTick(() => {
      measure()
    })
  })

  watch(container, () => {
    nextTick(measure)
  })

  onBeforeUnmount(() => {
    smoothScrolling = false
    clearSmoothWait()
  })

  const forceScroll = async () => {
    await nextTick()
    cancelSmoothScroll()
    jumpToBottom()
  }

  return { atBottom, showButton, scrollToBottom, forceScroll, measure }
}
