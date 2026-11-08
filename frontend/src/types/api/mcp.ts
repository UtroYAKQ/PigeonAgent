import type { UUID } from './common'

/** 前台选择器可用的 MCP 服务器；不含地址与凭证。 */
export interface McpServerOption {
  id: UUID
  name: string
  slug: string
  description: string | null
  requires_approval: boolean
  defer_loading: boolean
  tool_count: number
}

export interface McpToolInfo {
  name: string
  description: string | null
}

export interface McpServerTestResult {
  ok: boolean
  tools: McpToolInfo[]
  error: string | null
}

export interface AdminMcpServer {
  id: UUID
  name: string
  slug: string
  url: string
  description: string | null
  has_auth: boolean
  enabled: boolean
  requires_approval: boolean
  defer_loading: boolean
  timeout_seconds: number
  tool_count: number
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminMcpServerList {
  items: AdminMcpServer[]
  total: number
}

export interface AdminMcpServerCreatePayload {
  name: string
  slug: string
  url: string
  description?: string | null
  auth?: string
  enabled?: boolean
  requires_approval?: boolean
  defer_loading?: boolean
  timeout_seconds?: number
}

export type AdminMcpServerUpdatePayload = Omit<
  Partial<AdminMcpServerCreatePayload>,
  'auth'
> & {
  /** null 表示清除已保存的 Bearer Token；不传表示保持原值 */
  auth?: string | null
}
