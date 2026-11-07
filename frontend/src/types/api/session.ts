/* session 领域类型。 */

import type { UUID, TokenUsage } from './common'
import type { SessionRun } from './run'
import type { ThinkingLevel } from './model'

/** 一条只读分享链接；token 只在创建与「我的分享」列表里出现。 */
export interface SessionShare {
  id: UUID
  session_id: UUID
  session_title: string | null
  token: string
  expires_at: string
  visit_count: number
  last_visited_at: string | null
  created_at: string
}

/** 访客从公开链接读到的内容：会话只有认得出来的那几个字段。 */
export interface SharedConversation {
  session: {
    title: string | null
    created_at: string
    last_run_at: string
  }
  runs: SessionRun[]
  has_more: boolean
  expires_at: string
}

export type SessionStatus = 'active' | 'archived'

export interface ChatSession {
  id: UUID
  title: string | null
  model_id: number | null
  group_id: number | null
  status: SessionStatus
  format_version: number
  run_seq: number
  active_run_id: string | null
  active_run_expires_at: string | null
  active_leaf_run_id: UUID | null
  pending_batches: number
  has_unread: boolean
  thinking_level: ThinkingLevel | null
  usage: TokenUsage
  last_run_at: string
  created_at: string
  updated_at: string
}

export interface SessionList {
  items: ChatSession[]
  total: number
}

export interface SessionGroup {
  id: number
  name: string
  sort_order: number
  session_count: number
  created_at: string
  updated_at: string
}

export interface SessionCreatePayload {
  title?: string | null
  model_id?: number | null
  group_id?: number | null
  thinking_level?: ThinkingLevel | null
}

export interface SessionUpdatePayload {
  title?: string | null
  model_id?: number | null
  status?: SessionStatus
  group_id?: number | null
  thinking_level?: ThinkingLevel | null
}
