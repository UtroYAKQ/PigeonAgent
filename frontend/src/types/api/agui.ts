/* agui 领域类型。 */



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
