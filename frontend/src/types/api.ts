export type UUID = string

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type ThemePreference = 'light' | 'dark' | 'system'
export type SendShortcut = 'enter' | 'ctrl-enter'

export interface UserPreferences {
  theme: ThemePreference
  send_shortcut: SendShortcut
  auto_expand_thinking: boolean
  auto_expand_tool_details: boolean
  wrap_code: boolean
}

/** 账号显式存过的偏好；缺键表示这个账号在该项上没表过态，本地缓存继续生效。 */
export type StoredUserPreferences = Partial<UserPreferences>

export interface User {
  id: UUID
  email: string
  display_name: string | null
  avatar_file_id: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string
  credits_balance: number
  preferences: StoredUserPreferences
}

export interface RegisterResult {
  verification_required: boolean
  user?: User | null
  tokens?: TokenPair | null
}

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

export type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface LlmModel {
  id: number
  name: string
  provider: string
  icon: string | null
  model_name: string
  base_url: string | null
  context_window: number | null
  max_output_tokens: number | null
  compaction_threshold: number | null
  credit_input_per_1m: number | null
  credit_output_per_1m: number | null
  credit_cache_read_per_1m: number | null
  thinking_levels: ThinkingLevel[]
  supports_tools: boolean
  is_active: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface LlmModelList {
  items: LlmModel[]
  total: number
}

export interface LlmModelCreatePayload {
  name: string
  provider: string
  icon?: string | null
  model_name: string
  base_url?: string | null
  api_key?: string | null
  context_window?: number | null
  max_output_tokens?: number | null
  compaction_threshold?: number | null
  credit_input_per_1m?: number | null
  credit_output_per_1m?: number | null
  credit_cache_read_per_1m?: number | null
  thinking_levels?: ThinkingLevel[]
  supports_tools?: boolean
  is_active?: boolean
  is_default?: boolean
}

export type LlmModelUpdatePayload = Partial<LlmModelCreatePayload>

/* --------------------------------- image model ------------------------------- */

export interface ImageModel {
  id: number
  name: string
  provider: string
  protocol: string
  icon: string | null
  model_name: string
  base_url: string | null
  sizes: string[]
  default_size: string
  max_images: number
  quality: string | null
  credit_per_image: number | null
  is_active: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface ImageProviderPreset {
  key: string
  label: string
  protocol: string
  base_url: string | null
  path: string
  model_hint: string
  sizes: string[]
  note: string | null
}

export interface ImageModelList {
  items: ImageModel[]
  total: number
}

export interface ImageModelCreatePayload {
  name: string
  provider?: string
  protocol?: string
  icon?: string | null
  model_name: string
  base_url?: string | null
  api_key?: string | null
  sizes?: string[]
  default_size?: string
  max_images?: number
  quality?: string | null
  credit_per_image?: number | null
  is_active?: boolean
  is_default?: boolean
}

export type ImageModelUpdatePayload = Partial<ImageModelCreatePayload>


/* --------------------------------- app config -------------------------------- */

export type ConfigValueType = 'string' | 'secret' | 'int' | 'float' | 'bool'
export type ConfigSource = 'database' | 'environment' | 'default'

export interface AppConfigItem {
  key: string
  category: string
  category_label: string
  label: string
  description: string | null
  value_type: ConfigValueType
  is_secret: boolean
  choices: string[] | null
  value: string | null
  has_value: boolean
  source: ConfigSource
  sort_order: number
}

export interface AppConfigList {
  items: AppConfigItem[]
  total: number
}

export type SessionStatus = 'active' | 'archived'

export interface TokenUsage {
  requests: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  total_tokens: number
}

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

export interface FileRecord {
  id: UUID
  name: string
  size: number
  content_type: string | null
  sha256: string
}

/** 短时效对象存储媒体直链。 */
export interface FileLink {
  url: string
  expires_at: string
}

/* ---------------------------------- runs ---------------------------------- */

export type RunStatus = 'running' | 'completed' | 'interrupted' | 'failed' | 'cancelled'
export type RunKind = 'turn' | 'resume'

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

export interface ImageItem extends BaseItem {
  type: 'image'
  role: 'user' | 'assistant'
  url?: string | null
  data?: string | null
  file_id?: string | null
  media_type?: string | null
  alt?: string | null
}

export interface VideoItem extends BaseItem {
  type: 'video'
  role: 'user' | 'assistant'
  url?: string | null
  data?: string | null
  file_id?: string | null
  media_type?: string | null
  alt?: string | null
}

export interface FileItem extends BaseItem {
  type: 'file'
  role: 'user' | 'assistant'
  name: string
  media_type: string
  data: string
  size: number
}

export interface ResourceItem extends BaseItem {
  type: 'resource'
  role: 'user' | 'assistant'
  storage_key: string
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
  | FileItem
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
  kind: RunKind
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
  storage_key: string
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

export interface ImageModelOption {
  id: number
  name: string
  icon: string | null
  default_size: string
  sizes: string[]
  max_images: number
  is_default: boolean
}

export interface Capabilities {
  web_search: boolean
  image_generation: boolean
  image_models: ImageModelOption[]
  default_image_model_id: number | null
  max_upload_bytes: number
  max_image_attachments: number
  max_resource_files: number
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

/* -------------------------------- AG-UI SSE -------------------------------- */

/**
 * 后端 ag_ui.core.BaseEvent 的公共头。`type` 由各事件自己收窄成字面量，
 * 所以 AgUiEvent 是判别联合，switch 能按它分出具体分支。
 */
export interface AgUiBaseEvent {
  type: string
  timestamp?: number
}

export interface RunStartedEvent extends AgUiBaseEvent {
  type: 'RUN_STARTED'
  threadId: string
  runId: string
}

export interface RunFinishedEvent extends AgUiBaseEvent {
  type: 'RUN_FINISHED'
  threadId: string
  runId: string
  outcome?: { type: 'success' | 'interrupt'; interrupts?: unknown[] } | null
}

export interface RunErrorEvent extends AgUiBaseEvent {
  type: 'RUN_ERROR'
  message: string
  code?: string | null
}

export interface TextMessageStartEvent extends AgUiBaseEvent {
  type: 'TEXT_MESSAGE_START'
  messageId: string
  role?: string
}

export interface TextMessageContentEvent extends AgUiBaseEvent {
  type: 'TEXT_MESSAGE_CONTENT'
  messageId: string
  delta: string
}

export interface TextMessageEndEvent extends AgUiBaseEvent {
  type: 'TEXT_MESSAGE_END'
  messageId: string
}

/**
 * 思考流三件套。后端 ag-ui-protocol 0.1.22 走 pydantic-ai 的 `>= 0.1.11` 分支，
 * 只会发 REASONING_*；0.1.10 之前的 THINKING_TEXT_MESSAGE_* 不会再出现在这条流上。
 */
export interface ReasoningMessageStartEvent extends AgUiBaseEvent {
  type: 'REASONING_START' | 'REASONING_MESSAGE_START'
  messageId?: string
}

export interface ReasoningMessageContentEvent extends AgUiBaseEvent {
  type: 'REASONING_MESSAGE_CONTENT'
  messageId?: string
  delta: string
}

export interface ReasoningMessageEndEvent extends AgUiBaseEvent {
  type: 'REASONING_END' | 'REASONING_MESSAGE_END'
  messageId?: string
}

export interface ToolCallStartEvent extends AgUiBaseEvent {
  type: 'TOOL_CALL_START'
  toolCallId: string
  toolCallName: string
  parentMessageId?: string | null
}

export interface ToolCallArgsEvent extends AgUiBaseEvent {
  type: 'TOOL_CALL_ARGS'
  toolCallId: string
  delta: string
}

export interface ToolCallEndEvent extends AgUiBaseEvent {
  type: 'TOOL_CALL_END'
  toolCallId: string
}

export interface ToolCallResultEvent extends AgUiBaseEvent {
  type: 'TOOL_CALL_RESULT'
  toolCallId: string
  messageId?: string
  content: string
}

export interface ReasoningEncryptedValueEvent extends AgUiBaseEvent {
  type: 'REASONING_ENCRYPTED_VALUE'
  subtype: 'tool-call' | 'message'
  entityId: string
  encryptedValue: string
}

export interface CustomAgUiEvent extends AgUiBaseEvent {
  type: 'CUSTOM'
  name: string
  value: unknown
}

export type AgUiEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | RunErrorEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | ReasoningMessageStartEvent
  | ReasoningMessageContentEvent
  | ReasoningMessageEndEvent
  | ToolCallStartEvent
  | ToolCallArgsEvent
  | ToolCallEndEvent
  | ToolCallResultEvent
  | ReasoningEncryptedValueEvent
  | CustomAgUiEvent

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
  origin?: 'generated' | 'workspace'
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

export type AttachmentKind = 'image' | 'video' | 'resource'

export interface DraftAttachment {
  localId: string
  file: File
  kind: AttachmentKind
  previewUrl: string | null
  status: 'uploading' | 'ready' | 'error'
  record: FileRecord | null
  error: string | null
  progress: number
}

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

export interface UsageTotals {
  today_tokens: number
  today_credits: number
  today_cache_read_tokens: number
  month_tokens: number
  month_credits: number
  month_cache_read_tokens: number
  month_runs: number
  runs_total: number
  range_input_tokens: number
  range_output_tokens: number
  range_cache_read_tokens: number
  range_credits: number
}

export interface UsageDaily {
  date: string
  tokens: number
  credits: number
  runs: number
  cache_read_tokens: number
}

export interface UsageModelStat {
  model_name: string | null
  runs: number
  tokens: number
  credits: number
  cache_read_tokens: number
}

export interface UsageRecent {
  created_at: string
  model_name: string | null
  status: string
  total_tokens: number
  cache_read_tokens: number
  credits_charged: number
  images_generated: number
}

export interface UsageOverview {
  balance: number
  billing_enabled: boolean
  totals: UsageTotals
  daily: UsageDaily[]
  by_model: UsageModelStat[]
  recent: UsageRecent[]
}
