/** PigeonAgent API 的出参是 snake_case；AG-UI 事件是 camelCase。 */

export type InterruptKind = "call" | "approval";

export type RunStatus = "running" | "completed" | "interrupted" | "failed" | "cancelled";

export type RunKind = "turn" | "resume";

/** run 的 ToolCallItem 上声明的一个未决中断。 */
export interface PendingInterrupt {
  interrupt_id: string;
  tool_call_id: string;
  kind: InterruptKind;
}

export interface Session {
  id: string;
  title: string | null;
  model_id: number | null;
  /** 所属分组；null 表示未分组，侧栏按时间归档。 */
  group_id: number | null;
  status: "active" | "archived" | string;
  format_version: number;
  run_seq: number;
  active_run_id: string | null;
  active_run_expires_at?: string | null;
  /** 当前分支的叶子 run。 */
  active_leaf_run_id: string | null;
  /** 这个会话还有几个没解决的中断批次。 */
  pending_batches: number;
  usage?: Usage | null;
  last_run_at: string;
  created_at: string;
  updated_at: string;
}

export interface SessionList {
  items: Session[];
  total: number;
}

export interface SessionGroup {
  id: number;
  name: string;
  sort_order: number;
  /** 组内会话数，列表接口一次算好带回来。 */
  session_count: number;
  created_at: string;
  updated_at: string;
}

export interface SessionGroupList {
  items: SessionGroup[];
  total: number;
}

export interface LlmModel {
  id: number;
  name: string;
  provider: string;
  model_name: string;
  base_url: string | null;
  context_window: number | null;
  max_output_tokens: number | null;
  supports_tools: boolean;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface LlmModelList {
  items: LlmModel[];
  total: number;
}

export interface RunRead {
  run_id: string;
}

/** 待发送的图片/视频附件；file_id = /files 上传后的记录 id。 */
export interface OutgoingAttachment {
  kind: "image" | "video";
  name: string;
  media_type: string;
  file_id: string;
  size: number;
  preview?: string;
}

/** 已走 /files 上传成功的文件引用；随 RunCreate.resources 发出。 */
export interface OutgoingResource {
  storage_key: string;
  name: string;
  media_type: string;
  size: number;
  preview?: string;
}

/** POST /files 的回参；storage_key 就是这里的 id。 */
export interface FileRead {
  id: string;
  name: string;
  size: number;
  content_type: string | null;
  sha256: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserRead {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
}

/** 设置窗口左侧目录；加栏目先在这里加 id，再去 SettingsDialog 登记。 */
export type SettingsSection = "profile" | "models";

interface OneTimeRegisterResult {
  verifyRequired: boolean;
}

export type { OneTimeRegisterResult };

/** 每轮随请求上传的前端工具声明，后端据此建外部 toolset。 */
export interface FrontendToolDeclaration {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  total_tokens?: number;
  requests?: number;
  [key: string]: unknown;
}

/** ---------------- run.content 的类型化 item ---------------- */

export interface BaseRunItem {
  id: string;
  type: string;
  in_context: boolean;
  display: boolean;
  created_at: string;
}

export interface RunTextItem extends BaseRunItem {
  type: "text";
  role: "user" | "assistant" | "system";
  text: string;
}

export interface RunImageItem extends BaseRunItem {
  type: "image";
  role: "user" | "assistant";
  url?: string | null;
  data?: string | null;
  file_id?: string | null;
  media_type?: string | null;
  alt?: string | null;
}

export interface RunVideoItem extends BaseRunItem {
  type: "video";
  role: "user" | "assistant";
  url?: string | null;
  data?: string | null;
  file_id?: string | null;
  media_type?: string | null;
  alt?: string | null;
}

export interface RunThinkingItem extends BaseRunItem {
  type: "thinking";
  text: string;
}

export interface RunFileItem extends BaseRunItem {
  type: "file";
  role: "user" | "assistant";
  name: string;
  media_type: string;
  data: string;
  size: number;
}

/** 走 /files 上传（或产物回收）的文件引用；storageKey 就是文件 id。 */
export interface RunResourceItem extends BaseRunItem {
  type: "resource";
  role: "user" | "assistant";
  storage_key: string;
  name: string;
  media_type: string;
  size?: number | null;
}

export interface RunToolCallItem extends BaseRunItem {
  type: "tool_call";
  tool_call_id: string;
  tool_name: string;
  args: unknown;
}

export interface RunToolResultItem extends BaseRunItem {
  type: "tool_result";
  tool_call_id: string;
  tool_name: string;
  content: unknown;
  outcome: "success" | "failed" | "denied" | "interrupted" | "retried";
  metadata?: unknown;
}

export interface RunErrorItem extends BaseRunItem {
  type: "error";
  code: string;
  message: string;
  provider?: string | null;
  retryable?: boolean;
}

export interface RunApprovalRequestItem extends BaseRunItem {
  type: "approval_request";
  interrupt_id: string;
  tool_call_ids: string[];
}

export interface RunCallRequestItem extends BaseRunItem {
  type: "call_request";
  interrupt_id: string;
  tool_call_ids: string[];
  metadata?: Record<string, unknown> | null;
}

export interface RunCustomItem extends BaseRunItem {
  type: "custom";
  renderer: string;
  version?: number;
  data?: unknown;
  key?: string | null;
}

export type RunItem =
  | RunTextItem
  | RunImageItem
  | RunVideoItem
  | RunFileItem
  | RunResourceItem
  | RunThinkingItem
  | RunToolCallItem
  | RunToolResultItem
  | RunErrorItem
  | RunApprovalRequestItem
  | RunCallRequestItem
  | RunCustomItem
  | (BaseRunItem & { type: string; [key: string]: unknown });

export interface SessionRun {
  id: string;
  session_id: string;
  parent_run_id: string | null;
  seq: number;
  status: RunStatus;
  kind: RunKind;
  content: RunItem[];
  preview: string;
  usage: Usage;
  branch?: BranchNav | null;
  created_at: string;
  updated_at: string;
}

export interface RunList {
  items: SessionRun[];
  has_more?: boolean | null;
}

/** 工具结果里带回来的媒体；base64 会转成 data URL 再展示。 */
export interface ResultMedia {
  type: "image" | "video";
  url: string;
  mediaType?: string | null;
}

export interface ToolResult {
  status: "ok" | "error";
  content: string;
  error?: string | null;
  media?: ResultMedia[];
  files?: ResultFile[];
}

/** 工具结果里带回来的可下载文件；storageKey 对应 /files/{id}。 */
export interface ResultFile {
  storageKey: string;
  name: string;
  size?: number | null;
}

/** ---------------- 前端展示投影 ---------------- */

export interface TextItem {
  type: "text";
  id: string;
  text: string;
  role: "user" | "assistant";
  status: "streaming" | "done";
}

export interface ThinkingItem {
  type: "thinking";
  id: string;
  text: string;
  status: "streaming" | "done";
}

export interface ImageItem {
  type: "image";
  id: string;
  url: string;
  fileId?: string | null;
  mediaType?: string | null;
  alt?: string | null;
}

export interface VideoItem {
  type: "video";
  id: string;
  url: string;
  fileId?: string | null;
  mediaType?: string | null;
  alt?: string | null;
}

export interface FileItem {
  type: "file";
  id: string;
  name: string;
  mediaType?: string | null;
  size: number;
}

/** 文件资源 chip：点击下载，storageKey 对应 /files/{id}。 */
export interface ResourceItem {
  type: "resource";
  id: string;
  storageKey: string;
  name: string;
  mediaType?: string | null;
  size?: number | null;
}

/** 中断在 UI 上的结论：等待中 / 已允许 / 已拒绝 / 已回填 / 已取消。 */
export type InterruptState =
  | { kind: InterruptKind; status: "pending" }
  | { kind: "approval"; status: "approved" | "denied" }
  | { kind: "call"; status: "resolved" };

export interface ToolItem {
  type: "tool";
  id: string;
  toolCallId: string;
  name: string;
  args: string;
  argsParsed: Record<string, unknown> | null;
  result: ToolResult | null;
  status: "streaming" | "ready" | "done" | "error" | "interrupted";
  interrupt?: InterruptState | null;
}

export interface ErrorItem {
  type: "error";
  id: string;
  message: string;
  code?: string | null;
  retryable?: boolean;
}

export interface CustomItem {
  type: "custom";
  id: string;
  name: string;
  version?: number;
  value: unknown;
  status: "done";
}

export type Item =
  | TextItem
  | ThinkingItem
  | ImageItem
  | VideoItem
  | FileItem
  | ResourceItem
  | ToolItem
  | ErrorItem
  | CustomItem;

/** 同一处的多个用户轮次，用于「第 2 / 3 个答案」这类导航。 */
export interface BranchNav {
  position: number;
  total: number;
  /** 每个分支的末端 run id：点哪个就切到哪个分支。 */
  leaves: string[];
}

export interface DisplayBlock {
  id: string;
  role: "user" | "assistant";
  items: Item[];
  status: "streaming" | "done" | "error";
  usage?: Usage | null;
  created_at?: string;
  /** 组成这个块的 run（通常是一条）。 */
  runIds: string[];
  /** 用户块所属 run；助手块用来定位回答的是哪条 turn。 */
  runId?: string;
  parentRunId?: string | null;
  /** 这条回答是在回答哪条用户 run：重新生成从它的父节点另起分支。 */
  answerTo?: string | null;
  branch?: BranchNav | null;
  /** 组成这个块的最后一条 run 被中断（用户点了停止）。 */
  interrupted?: boolean;
}

/** 审批面板要用工具名和参数，得从 ToolCallItem 里取。 */
export interface InterruptView extends PendingInterrupt {
  name: string;
  args: string;
  argsParsed: Record<string, unknown> | null;
  /** Call 的来源信息，来自 CallRequestItem.metadata[tool_call_id]。 */
  meta: Record<string, unknown> | null;
}

export interface AguiEvent {
  type: string;
  messageId?: string;
  parentMessageId?: string;
  role?: string;
  delta?: string;
  toolCallId?: string;
  toolCallName?: string;
  content?: unknown;
  name?: string;
  value?: unknown;
  message?: string;
  code?: string | null;
  result?: unknown;
  snapshot?: unknown;
  isError?: boolean;
  [key: string]: unknown;
}
