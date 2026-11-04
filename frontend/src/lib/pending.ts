import type { SessionRun, ToolCallItem, ToolResultItem } from '@/types/api'
import type { AskQuestion, PreviewPayload } from './frontendTools'
import { ASK_TOOL, PREVIEW_TOOL, parseAskArgs, parsePreviewArgs } from './frontendTools'

export interface PendingTool {
  toolCallId: string
  toolName: string
  args: unknown
  metadata: unknown
  kind: 'approval' | 'call'
  result: ToolResultItem | null
}

export interface PendingBatch {
  runId: string
  interruptId: string
  approvals: PendingTool[]
  calls: PendingTool[]
  pendingApprovals: PendingTool[]
  pendingCalls: PendingTool[]
  resolved: boolean
}

export function buildPendingBatches(
  run: SessionRun,
  resultsByCallId: Map<string, ToolResultItem>,
): PendingBatch[] {
  const callItems = new Map<string, ToolCallItem>()
  const batches = new Map<string, {
    interruptId: string
    approvals: string[]
    calls: string[]
    metadata: Record<string, unknown>
  }>()

  for (const item of run.content) {
    if (item.type === 'tool_call') {
      callItems.set(item.tool_call_id, item)
    } else if (item.type === 'approval_request' || item.type === 'call_request') {
      let batch = batches.get(item.interrupt_id)
      if (!batch) {
        batch = { interruptId: item.interrupt_id, approvals: [], calls: [], metadata: {} }
        batches.set(item.interrupt_id, batch)
      }
      if (item.type === 'approval_request') {
        batch.approvals.push(...item.tool_call_ids)
      } else {
        batch.calls.push(...item.tool_call_ids)
        const metadata = item.metadata
        if (metadata && typeof metadata === 'object') {
          Object.assign(batch.metadata, metadata as Record<string, unknown>)
        }
      }
    }
  }

  return [...batches.values()].map((batch) => {
    const toTool = (id: string, kind: 'approval' | 'call'): PendingTool => {
      const call = callItems.get(id)
      return {
        toolCallId: id,
        toolName: call?.tool_name ?? 'tool',
        args: call?.args ?? null,
        metadata: batch.metadata[id] ?? null,
        kind,
        result: resultsByCallId.get(id) ?? null,
      }
    }
    const approvals = batch.approvals.map(id => toTool(id, 'approval'))
    const calls = batch.calls.map(id => toTool(id, 'call'))
    const pendingApprovals = approvals.filter(item => !item.result)
    const pendingCalls = calls.filter(item => !item.result)
    return {
      runId: run.id,
      interruptId: batch.interruptId,
      approvals,
      calls,
      pendingApprovals,
      pendingCalls,
      resolved: pendingApprovals.length === 0 && pendingCalls.length === 0,
    }
  })
}

export function previewPayload(tool: PendingTool): PreviewPayload | null {
  if (tool.toolName !== PREVIEW_TOOL) return null
  return parsePreviewArgs(tool.args)
}

export function isPreviewTool(name: string): boolean {
  return name === PREVIEW_TOOL
}

export function isAskTool(name: string): boolean {
  return name === ASK_TOOL
}

/** 提问调用解析成问卷；形状不对就交回通用结果输入，不渲染半张卡。 */
export function askQuestions(tool: PendingTool): AskQuestion[] | null {
  if (!isAskTool(tool.toolName)) return null
  return parseAskArgs(tool.args)
}

export function isPreviewOnlyBatch(batch: PendingBatch): boolean {
  return batch.pendingApprovals.length === 0
    && batch.pendingCalls.length > 0
    && batch.pendingCalls.every(tool => isPreviewTool(tool.toolName))
}
