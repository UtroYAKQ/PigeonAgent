import type { DraftAttachment, RunCreatePayload, UUID } from '@/types/api'
import { FRONTEND_TOOLS } from '@/lib/frontendTools'

export interface SendMessageInput {
  text: string
  attachments?: DraftAttachment[]
  parentRunId?: UUID | null
  retryRunId?: UUID
  groupId?: number | null
}

export interface RunPayloadContext {
  currentModelId: number | null
  effectiveWebSearch: boolean
  effectiveImageGeneration: boolean
  currentImageModelId: number | null
  maxImageAttachments: number
  maxResourceFiles: number
}

/** 开关状态原样下发：后端默认值各不相同，省略字段可能把用户关掉的开关又打开。 */
export function buildRunFlags(
  context: RunPayloadContext,
): Pick<RunCreatePayload, 'enable_web_search' | 'enable_image_generation' | 'image_model_id'> {
  return {
    enable_web_search: context.effectiveWebSearch,
    enable_image_generation: context.effectiveImageGeneration,
    image_model_id: context.effectiveImageGeneration ? context.currentImageModelId : null,
  }
}

export function buildRunPayload(
  input: SendMessageInput,
  context: RunPayloadContext,
): RunCreatePayload {
  const flags = buildRunFlags(context)
  if (input.retryRunId) {
    return {
      retry_run_id: input.retryRunId,
      model_id: context.currentModelId ?? undefined,
      tools: FRONTEND_TOOLS,
      ...flags,
    }
  }

  const attachments = (input.attachments ?? [])
    .filter(
      item =>
        item.status === 'ready' &&
        item.record &&
        (item.kind === 'image' || item.kind === 'video'),
    )
    .slice(0, context.maxImageAttachments)
    .map(item => ({
      kind: item.kind as 'image' | 'video',
      name: item.record?.name ?? item.file.name,
      media_type: item.record?.content_type || item.file.type || 'application/octet-stream',
      file_id: item.record!.id,
    }))

  const resources = (input.attachments ?? [])
    .filter(item => item.status === 'ready' && item.record && item.kind === 'resource')
    .slice(0, context.maxResourceFiles)
    .map(item => ({
      file_id: item.record!.id,
      name: item.record?.name ?? item.file.name,
    }))

  const payload: RunCreatePayload = {
    model_id: context.currentModelId ?? undefined,
    attachments,
    resources,
    tools: FRONTEND_TOOLS,
    ...flags,
  }
  if (input.text.trim()) payload.input = input.text.trim()
  if (input.parentRunId !== undefined) payload.parent_run_id = input.parentRunId
  return payload
}
