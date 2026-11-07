/* admin 领域类型。 */

import type { UUID, TokenUsage } from './common'
import type { SessionStatus } from './session'

/* ------------------------------- platform admin ------------------------------ */

export interface AdminStats {
  users_total: number
  users_active: number
  users_admin: number
  sessions_total: number
  sessions_active: number
  sessions_archived: number
  runs_total: number
  runs_failed: number
}

export interface AdminUser {
  id: UUID
  email: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  email_verified: boolean
  created_at: string
  session_count: number
  last_active_at: string | null
  credits_balance: number
}

export interface AdminUserList {
  items: AdminUser[]
  total: number
}

export interface AdminCreditLog {
  id: UUID
  user_id: UUID | null
  user_email: string | null
  user_display_name: string | null
  delta: number
  balance_after: number
  reason: 'chat' | 'image' | 'adjust'
  run_id: UUID | null
  model_kind: string | null
  model_id: number | null
  usage: Record<string, number>
  note: string | null
  created_at: string
}

export interface AdminCreditLogList {
  items: AdminCreditLog[]
  total: number
}

export interface AdminChatLog {
  id: UUID
  user_id: UUID | null
  user_email: string | null
  user_display_name: string | null
  session_id: UUID | null
  run_id: UUID | null
  kind: string
  status: string
  model_name: string | null
  usage: TokenUsage
  credits_charged: number
  images_generated: number
  error: string | null
  duration_ms: number | null
  created_at: string
  finished_at: string | null
}

export interface AdminChatLogList {
  items: AdminChatLog[]
  total: number
}

export interface AdminUserUpdatePayload {
  display_name?: string | null
  is_admin?: boolean
  is_active?: boolean
}

export interface AdminSession {
  id: UUID
  title: string | null
  owner_id: UUID | null
  owner_email: string | null
  owner_display_name: string | null
  status: SessionStatus
  model_id: number | null
  has_unread: boolean
  active_run_id: string | null
  usage: TokenUsage
  run_count: number
  last_run_at: string
  created_at: string
}

export interface AdminSessionList {
  items: AdminSession[]
  total: number
}

export interface AdminOperationLog {
  id: number
  request_id: string | null
  kind: 'request' | 'admin'
  actor_email: string | null
  method: string | null
  path: string | null
  route: string | null
  query: unknown
  request_body: unknown
  status_code: number | null
  response_body: unknown
  duration_ms: number | null
  request_bytes: number
  response_bytes: number
  request_truncated: boolean
  response_truncated: boolean
  client_ip: string | null
  user_agent: string | null
  action: string | null
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

export interface AdminOperationLogList {
  items: AdminOperationLog[]
  total: number
}
