/* live 领域类型。 */

import type { UUID, TokenUsage } from './common'

/* ------------------------------- local models ------------------------------- */

export type LiveBlockKind = 'reasoning' | 'text' | 'tool' | 'artifact'

/** 生成产物的轻量描述；字节由 file_id 走带鉴权的下载接口取 */
export interface LiveMedia {
  file_id: string
  media_type: string
  name: string
  size: number
  alt: string | null
  /** generated = 出图工具；workspace = 沙箱发布 */
  origin: 'generated' | 'workspace'
}

export interface LiveToolState {
  toolCallId: string
  name: string
  argsText: string
  resultText?: string
  resultMessageId?: string
  state: 'running' | 'waiting' | 'success' | 'failed' | 'interrupted'
}

export interface LiveBlock {
  id: string
  kind: LiveBlockKind
  text?: string
  tool?: LiveToolState
  message?: string
  media?: LiveMedia[]
  streaming?: boolean
}

export interface LiveCompaction {
  status: 'running' | 'done'
  summary: string | null
  tokensBefore: number | null
}

export interface LiveRun {
  runId: string
  sessionId: UUID
  blocks: LiveBlock[]
  usage: TokenUsage | null
  compaction: LiveCompaction | null
  error: string | null
  errorCode?: string | null
  connected: boolean
  finished: boolean
}
