export const ERROR_CODES = ['401', '403', '404', '500', '503'] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

/** 每个错误码对应一套视觉；读屏用的 reason 由它派生，不再单列一套并行枚举。 */
export type ErrorVariant = 'unauthorized' | 'forbidden' | 'lost' | 'broken' | 'paused'

export type ErrorActionKind = 'home' | 'back'

export interface ErrorAction {
  label: string
  kind: ErrorActionKind
  variant?: 'default' | 'outline'
}

export interface ErrorPageContent {
  code: ErrorCode
  reason: string
  variant: ErrorVariant
  title: string
  description: string
  actions: ErrorAction[]
}

const ACTIONS: ErrorAction[] = [
  { label: '返回上一页', kind: 'back', variant: 'outline' },
  { label: '回到首页', kind: 'home' },
]

const REASONS: Record<ErrorVariant, string> = {
  unauthorized: '未登录',
  forbidden: '没有权限',
  lost: '页面不存在',
  broken: '服务器出错',
  paused: '服务暂不可用',
}

const ERROR_PAGES: Record<ErrorCode, Omit<ErrorPageContent, 'reason' | 'actions'>> = {
  401: {
    code: '401',
    variant: 'unauthorized',
    title: '需要登录',
    description: '这个页面要登录后才能看，请登录后再继续。',
  },
  403: {
    code: '403',
    variant: 'forbidden',
    title: '没有权限',
    description: '当前账号没有访问这个页面的权限，需要管理员开通。',
  },
  404: {
    code: '404',
    variant: 'lost',
    title: '页面不存在',
    description: '你要找的页面可能已经被删除、改过地址，或者从来就没有存在过。',
  },
  500: {
    code: '500',
    variant: 'broken',
    title: '服务器出错',
    description: '服务端遇到了没有预料到的情况，这次请求没能完成，请稍后重试。',
  },
  503: {
    code: '503',
    variant: 'paused',
    title: '服务暂不可用',
    description: '服务端正在维护或暂时过载，稍等片刻再试。',
  },
}

export function resolveErrorPage(code?: string | null): ErrorPageContent {
  const page = ERROR_PAGES[(code ?? '') as ErrorCode] ?? ERROR_PAGES['404']
  return { ...page, reason: REASONS[page.variant], actions: ACTIONS }
}
