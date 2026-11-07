import type { ChatSession, SessionRun } from '@/types/api'

export const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export const SESSION_PAGE_SIZE = 50
export const SEARCH_PAGE_SIZE = 50
// 打开会话先取最近这么多条 run 渲染历史；开轮后的刷新与超时收尾各自要的窗口不同。
// 手机首屏少渲染一些历史，"加载更早"随时补得回来。
export const RUNS_PAGE_SIZE = 40
export const RUNS_PAGE_SIZE_COMPACT = 24
export const RUNS_REFRESH_PAGE_SIZE = 60
export const RUNS_REFRESH_PAGE_SIZE_COMPACT = 32
export const RUNS_SETTLE_PAGE_SIZE = 80
export const RUNS_SETTLE_PAGE_SIZE_COMPACT = 40

export function runsPageSize(full: number, compact: number): number {
  if (typeof window === 'undefined') return full
  return window.matchMedia('(max-width: 767px)').matches ? compact : full
}

// 事件流断了也要确认后端真的结束：首轮快查，之后指数退避，总时长封顶
export const SETTLE_FIRST_DELAY_MS = 180
export const SETTLE_MAX_DELAY_MS = 15_000
export const SETTLE_TIMEOUT_MS = 5 * 60_000

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function mergeSessionHead(head: ChatSession[], current: ChatSession[]): ChatSession[] {
  const headIds = new Set(head.map(item => item.id))
  return [...head, ...current.filter(item => !headIds.has(item.id))]
}

/** 同一 run 续写过（内容里留有请求批次）就说明当前 live 流只是续写段。 */
export function runHasResumeMarker(run: SessionRun | undefined): boolean {
  return Boolean(
    run?.content.some(item => item.type === 'approval_request' || item.type === 'call_request'),
  )
}
