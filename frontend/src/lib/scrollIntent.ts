/** 滚动意图广播：数据层说「该滚了」，视图层决定怎么滚。 */

type Listener = (smooth: boolean) => void

const listeners = new Set<Listener>()

/** 视图层订阅；返回退订函数，随组件卸载调用。 */
export function onScrollIntent(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function requestScroll(smooth = false): void {
  for (const listener of listeners) listener(smooth)
}
