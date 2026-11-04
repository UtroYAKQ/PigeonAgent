/** 输入框"飞走"的动效：FLIP 位移加一串拖尾光点。这里只管怎么飞，何时飞由视图决定。 */

import { nextTick, ref } from 'vue'
import type { Ref } from 'vue'

const TRAIL_DOTS = 7
const TRAIL_DURATION_MS = 620
const TRAIL_STAGGER_MS = 35
const LANDING_DURATION_MS = 780
// 与 styles 里的 --motion-ease-flight 同一条曲线；Web Animations 拿不到 CSS 变量，改时要两处一起对
const LANDING_EASING = 'cubic-bezier(0.22, 1, 0.36, 1)'

export function useComposerFlight(inner: Ref<HTMLElement | null>) {
  const landing = ref(false)
  let cleanup: (() => void) | null = null

  function trailLayer(source: DOMRect, target: DOMRect): HTMLElement {
    const layer = document.createElement('div')
    layer.className = 'composer-flight-trail'
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:85;overflow:hidden;'
    const startX = source.left + source.width / 2
    const startY = source.top + source.height / 2
    const endX = target.left + target.width / 2
    const endY = target.top + target.height / 2
    for (let index = 0; index < TRAIL_DOTS; index += 1) {
      const progress = (index + 1) / (TRAIL_DOTS + 1)
      const size = index % 3 === 0 ? 4 : 3
      const x = startX + (endX - startX) * progress + Math.sin((index + 1) * 1.5) * 20
      const y = startY + (endY - startY) * progress
      const dot = document.createElement('span')
      dot.style.cssText = `position:fixed;left:${x - size / 2}px;top:${y - size / 2}px;width:${size}px;height:${size}px;border-radius:999px;background:var(--foreground);opacity:0;`
      layer.appendChild(dot)
      dot.animate(
        [
          { opacity: 0, transform: 'scale(0.4)' },
          { opacity: 0.22, transform: 'scale(1)', offset: 0.35 },
          { opacity: 0, transform: 'scale(0.5)' },
        ],
        {
          duration: TRAIL_DURATION_MS,
          delay: index * TRAIL_STAGGER_MS,
          easing: 'ease-out',
          fill: 'both',
        },
      )
    }
    document.body.appendChild(layer)
    return layer
  }

  function play(firstRect: DOMRect): void {
    const element = inner.value
    if (!element) {
      landing.value = false
      return
    }
    const lastRect = element.getBoundingClientRect()
    if (lastRect.width <= 0 || firstRect.width <= 0) {
      landing.value = false
      return
    }

    const dx = firstRect.left - lastRect.left
    const dy = firstRect.top - lastRect.top
    const scaleX = firstRect.width / lastRect.width

    element.style.transformOrigin = 'top left'
    const trail = trailLayer(firstRect, lastRect)
    const animation = element.animate(
      [
        { transform: `translate3d(${dx}px, ${dy}px, 0) scaleX(${scaleX})`, offset: 0 },
        {
          transform: `translate3d(${dx}px, ${dy - 9}px, 0) scaleX(${scaleX + (1 - scaleX) * 0.18})`,
          offset: 0.14,
        },
        { transform: 'none', offset: 1 },
      ],
      { duration: LANDING_DURATION_MS, easing: LANDING_EASING },
    )
    cleanup = () => {
      landing.value = false
      trail.remove()
      cleanup = null
    }
    animation.finished.then(end).catch(end)
  }

  function end(): void {
    cleanup?.()
  }

  /** 发送后调用：先立起 landing 让布局留出位置，再等 DOM 更新完做位移。 */
  function begin(firstRect: DOMRect): void {
    landing.value = true
    void nextTick().then(() => play(firstRect))
  }

  function cancel(): void {
    end()
  }

  return { landing, begin, cancel }
}
