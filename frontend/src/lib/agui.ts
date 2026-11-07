/** AG-UI 事件流 → LiveRun 视图模型的映射；store 只负责持有 liveRun，更新逻辑全在这里。 */

import type { AgUiEvent, LiveMedia, LiveRun, TokenUsage } from '@/types/api'
import { encryptedToolOutcome } from '@/lib/toolOutcome'

/** 连续到达的产物并进同一个块，一次生成多张就是一张网格。 */
function appendArtifactMedia(live: LiveRun, media: LiveMedia[]): void {
  if (!media.length) return
  const last = live.blocks[live.blocks.length - 1]
  if (last?.kind === 'artifact' && last.media) last.media.push(...media)
  else {
    live.blocks.push({
      id: `artifact-${media[0].file_id}`,
      kind: 'artifact',
      media: [...media],
    })
  }
}

export function applyAgUiEvent(
  live: LiveRun,
  event: AgUiEvent,
  resolveToolName?: (toolCallId: string) => string | undefined,
): void {
  switch (event.type) {
    case 'RUN_STARTED':
      live.connected = true
      break
    case 'RUN_FINISHED':
      live.finished = true
      if (live.compaction?.status === 'running') live.compaction = null
      break
    case 'RUN_ERROR':
      live.error = event.message || '运行失败'
      live.errorCode = event.code ?? null
      live.finished = true
      if (live.compaction?.status === 'running') live.compaction = null
      break
    case 'REASONING_START':
    case 'REASONING_MESSAGE_START': {
      const id = event.messageId || 'reasoning'
      const existing = live.blocks.find(block => block.kind === 'reasoning' && block.id === id)
      if (existing) existing.streaming = true
      else live.blocks.push({ id, kind: 'reasoning', text: '', streaming: true })
      break
    }
    case 'REASONING_MESSAGE_CONTENT': {
      const id = event.messageId || 'reasoning'
      let block = live.blocks.find(item => item.kind === 'reasoning' && item.id === id)
      if (!block) {
        block = { id, kind: 'reasoning', text: '', streaming: true }
        live.blocks.push(block)
      }
      block.text = (block.text ?? '') + event.delta
      break
    }
    case 'REASONING_END':
    case 'REASONING_MESSAGE_END': {
      const id = event.messageId || 'reasoning'
      const block = live.blocks.find(item => item.kind === 'reasoning' && item.id === id)
      if (block) block.streaming = false
      break
    }
    case 'TEXT_MESSAGE_START': {
      const id = event.messageId
      const existing = live.blocks.find(block => block.kind === 'text' && block.id === id)
      if (existing) existing.streaming = true
      else live.blocks.push({ id, kind: 'text', text: '', streaming: true })
      break
    }
    case 'TEXT_MESSAGE_CONTENT': {
      const id = event.messageId
      let block = live.blocks.find(item => item.kind === 'text' && item.id === id)
      if (!block) {
        block = { id, kind: 'text', text: '', streaming: true }
        live.blocks.push(block)
      }
      block.text = (block.text ?? '') + event.delta
      break
    }
    case 'TEXT_MESSAGE_END': {
      const block = live.blocks.find(item => item.kind === 'text' && item.id === event.messageId)
      if (block) block.streaming = false
      break
    }
    case 'TOOL_CALL_START': {
      const id = event.toolCallId
      const existing = live.blocks.find(block => block.kind === 'tool' && block.id === id)
      if (!existing) {
        live.blocks.push({
          id,
          kind: 'tool',
          tool: {
            toolCallId: id,
            name: event.toolCallName || 'tool',
            argsText: '',
            state: 'running',
          },
        })
      }
      break
    }
    case 'TOOL_CALL_ARGS': {
      const block = live.blocks.find(item => item.kind === 'tool' && item.id === event.toolCallId)
      if (block?.tool) block.tool.argsText += event.delta
      break
    }
    case 'TOOL_CALL_END': {
      const block = live.blocks.find(item => item.kind === 'tool' && item.id === event.toolCallId)
      if (block?.tool && block.tool.state === 'running') block.tool.state = 'waiting'
      break
    }
    case 'TOOL_CALL_RESULT': {
      let block = live.blocks.find(item => item.kind === 'tool' && item.id === event.toolCallId)
      if (!block) {
        // resume 的结果没有对应的 TOOL_CALL_START（call 在上一段 run 里）；
        // 补一个同 id 的块，mergeTurnViews 才能把结果并回原步骤
        block = {
          id: event.toolCallId,
          kind: 'tool',
          tool: {
            toolCallId: event.toolCallId,
            name: resolveToolName?.(event.toolCallId) ?? 'tool',
            argsText: '',
            state: 'success',
          },
        }
        live.blocks.push(block)
      }
      if (block.tool) {
        block.tool.resultText = event.content
        if (event.messageId) block.tool.resultMessageId = event.messageId
        block.tool.state = 'success'
      }
      break
    }
    case 'REASONING_ENCRYPTED_VALUE': {
      // 只有 outcome 声明挂在 message 上；tool-call 的那条带的是工具种类，前端用不上
      if (event.subtype !== 'message') break
      const outcome = encryptedToolOutcome(event.encryptedValue)
      if (!outcome) break
      const block = live.blocks.find(item => item.kind === 'tool' && item.tool?.resultMessageId === event.entityId)
      if (!block?.tool) break
      if (outcome === 'failed' || outcome === 'denied') block.tool.state = 'failed'
      else if (outcome === 'interrupted') block.tool.state = 'interrupted'
      break
    }
    case 'CUSTOM': {
      if (event.name === 'run_usage') {
        const value = event.value as { usage?: TokenUsage } | null
        if (value?.usage) live.usage = value.usage
      } else if (event.name === 'image_generated' || event.name === 'artifact') {
        const value = event.value as { media?: LiveMedia | LiveMedia[] } | null
        const media = value?.media
        appendArtifactMedia(live, media ? (Array.isArray(media) ? media : [media]) : [])
      } else if (event.name === 'compaction_start') {
        const value = event.value as { estimated_tokens?: number } | null
        live.compaction = {
          status: 'running',
          summary: null,
          tokensBefore: value?.estimated_tokens ?? null,
        }
      } else if (event.name === 'compaction_result') {
        const value = event.value as { summary?: string; tokens_before?: number } | null
        live.compaction = {
          status: 'done',
          summary: value?.summary ?? null,
          tokensBefore: value?.tokens_before ?? live.compaction?.tokensBefore ?? null,
        }
      }
      break
    }
    default:
      break
  }
}
