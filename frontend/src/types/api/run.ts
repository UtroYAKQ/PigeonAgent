/* run 领域类型。 */

import type { UUID, TokenUsage } from './common'

/* ---------------------------------- runs ---------------------------------- */

export type RunStatus = 'running' | 'completed' | 'interrupted' | 'failed' | 'cancelled'

export interface BranchNav {
  position: number
  total: number
  leaves: UUID[]
}

interface BaseItem {
  id: UUID
  in_context: boolean
  display: boolean
  created_at: string
}

export interface TextItem extends BaseItem {
  type: 'text'
  role: 'user' | 'assistant' | 'system'
  text: string
  part_id?: string | null
  provider_name?: string | null
  provider_details?: Record<string, unknown> | null
}

interface FileMediaItem extends BaseItem {
  file_id: string
  name: string
  media_type: string
  size: number
}

export interface ImageItem extends FileMediaItem {
  type: 'image'
  role: 'user' | 'assistant'
  alt?: string | null
}

export interface VideoItem extends FileMediaItem {
  type: 'video'
  role: 'user' | 'assistant'
  alt?: string | null
}

export interface ResourceItem extends FileMediaItem {
  type: 'resource'
  role: 'user' | 'assistant'
}

export interface FileRef {
  file_id: string
  name: string
  media_type: string
  size: number
}

export interface ThinkingItem extends BaseItem {
  type: 'thinking'
  text: string
  part_id?: string | null
  signature?: string | null
  provider_name?: string | null
  provider_details?: Record<string, unknown> | null
}

export interface ToolCallItem extends BaseItem {
  type: 'tool_call'
  tool_call_id: string
  tool_name: string
  args: unknown
  part_id?: string | null
  provider_name?: string | null
  provider_details?: Record<string, unknown> | null
}

export type ToolOutcome = 'success' | 'failed' | 'denied' | 'interrupted' | 'retried'

export interface ToolResultItem extends BaseItem {
  type: 'tool_result'
  tool_call_id: string
  tool_name: string
  content: unknown
  outcome: ToolOutcome
  metadata?: unknown
  media?: FileRef[]
}

export interface ErrorItem extends BaseItem {
  type: 'error'
  code: string
  message: string
  provider?: string | null
  retryable: boolean
}

export interface ApprovalRequestItem extends BaseItem {
  type: 'approval_request'
  interrupt_id: UUID
  tool_call_ids: string[]
}

export interface CallRequestItem extends BaseItem {
  type: 'call_request'
  interrupt_id: UUID
  tool_call_ids: string[]
  metadata?: unknown
}

export interface CompactionItem extends BaseItem {
  type: 'compaction'
  summary: string
  tokens_before: number
  items_compacted: number
}

export interface CustomItem extends BaseItem {
  type: 'custom'
  renderer: string
  version: number
  data: unknown
  key?: string | null
}

export type RunItem =
  | TextItem
  | ImageItem
  | VideoItem
  | ResourceItem
  | ThinkingItem
  | ToolCallItem
  | ToolResultItem
  | ErrorItem
  | ApprovalRequestItem
  | CallRequestItem
  | CompactionItem
  | CustomItem

export interface SessionRun {
  id: UUID
  session_id: UUID
  parent_run_id: UUID | null
  seq: number
  status: RunStatus
  content: RunItem[]
  preview: string
  usage: TokenUsage
  compacted: boolean
  branch: BranchNav | null
  created_at: string
  updated_at: string
}

export interface SessionRunList {
  items: SessionRun[]
  has_more: boolean | null
}

/* ------------------------------ request bodies ----------------------------- */

export interface AttachmentPayload {
  kind: 'image' | 'video'
  name: string
  media_type: string
  file_id: string
}

export interface ResourcePayload {
  file_id: string
  name?: string | null
}

export interface FrontendToolDecl {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface RunCreatePayload {
  input?: string
  attachments?: AttachmentPayload[]
  resources?: ResourcePayload[]
  parent_run_id?: UUID | null
  retry_run_id?: UUID
  model_id?: number | null
  tools?: FrontendToolDecl[]
  enable_web_search?: boolean
  enable_image_generation?: boolean
  image_model_id?: number | null
}

export interface ResumeRunPayload {
  interrupt_id: UUID
  approvals: Record<string, boolean>
  calls: Record<string, unknown>
  tools?: FrontendToolDecl[]
  enable_web_search?: boolean
  enable_image_generation?: boolean
  image_model_id?: number | null
  model_id?: number | null
}
