import { onScopeDispose, ref } from 'vue'

import { copyToClipboard } from '@/lib/clipboard'

/** 复制成功的视觉反馈：copied 亮 1.4 秒；定时器随组件卸载自动清理。 */
export function useCopyFeedback() {
  const copied = ref(false)
  let timer: number | null = null

  onScopeDispose(() => {
    if (timer !== null) window.clearTimeout(timer)
  })

  async function copyText(text: string, onError?: () => void): Promise<boolean> {
    if (!(await copyToClipboard(text))) {
      onError?.()
      return false
    }
    copied.value = true
    if (timer !== null) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      copied.value = false
      timer = null
    }, 1400)
    return true
  }

  return { copied, copyText }
}
