import type {
  CompactionItem,
  ErrorItem,
  ImageItem,
  LiveBlock,
  LiveRun,
  ResourceItem,
  SessionRun,
  ToolResultItem,
  VideoItem,
} from '@/types/api'
import { buildToolSteps, liveToolStep, mediaKind, toolLabel, type ToolStep } from '@/lib/tools'
import type { ArtifactMedia, TurnSource, TurnView } from './types'

export interface HistorySources {
  sources: TurnSource[]
  error: ErrorItem | null
  compactions: CompactionItem[]
  interrupted: boolean
}

function mediaFromItem(item: ImageItem | VideoItem | ResourceItem): ArtifactMedia {
  return {
    id: item.id,
    kind: mediaKind(item.media_type),
    origin: item.type === 'resource' ? 'workspace' : 'generated',
    mediaType: item.media_type,
    fileId: item.file_id,
    name: item.name,
    size: item.size,
    alt: item.type === 'resource' ? null : (item.alt ?? null),
  }
}

function mediaFromLive(media: NonNullable<LiveBlock['media']>[number]): ArtifactMedia {
  return {
    id: media.file_id,
    kind: mediaKind(media.media_type),
    origin: media.origin,
    mediaType: media.media_type,
    fileId: media.file_id,
    name: media.name,
    size: media.size,
    alt: media.alt,
  }
}

/** 已经结束的 run 里没有结果的工具不会继续执行；别让 UI 一直停留在“正在…”。 */
function settleSteps(steps: ToolStep[], status: SessionRun['status']): ToolStep[] {
  if (status === 'running') return steps
  const finished = status === 'completed' || status === 'failed'
  const fallback = finished ? ('failed' as const) : ('interrupted' as const)
  return steps.map(step => (step.result
    ? step
    : { ...step, state: fallback, label: toolLabel(step.name, fallback) }))
}

export function historySources(
  run: SessionRun,
  externalResults?: Map<string, ToolResultItem>,
): HistorySources {
  const steps = settleSteps(buildToolSteps(run.content, externalResults), run.status)
  const stepById = new Map(steps.map(step => [step.id, step]))
  const usedSteps = new Set<string>()
  const sources: TurnSource[] = []
  const compactions: CompactionItem[] = []
  let error: ErrorItem | null = null
  let interrupted = run.status === 'interrupted'

  for (const item of run.content) {
    if (item.display === false) continue
    switch (item.type) {
      case 'text':
        if (item.role === 'assistant' && item.text) {
          sources.push({ kind: 'text', id: item.id, text: item.text, streaming: false })
        }
        break
      case 'thinking':
        if (item.text) {
          sources.push({ kind: 'reasoning', id: item.id, text: item.text, streaming: false })
        }
        break
      case 'tool_call': {
        const step = stepById.get(item.tool_call_id)
        if (step && !usedSteps.has(step.id)) {
          usedSteps.add(step.id)
          sources.push({ kind: 'tool', step })
        }
        break
      }
      case 'tool_result':
        break
      case 'image':
      case 'video':
        if (item.role === 'assistant') {
          sources.push({ kind: 'media', media: mediaFromItem(item) })
        }
        break
      case 'resource':
        if (item.role === 'assistant') {
          sources.push({ kind: 'media', media: mediaFromItem(item) })
        }
        break
      case 'error':
        error = item
        break
      case 'approval_request':
      case 'call_request':
        interrupted = true
        break
      case 'compaction':
        compactions.push(item)
        break
      case 'custom':
        sources.push({ kind: 'custom', id: item.id, renderer: item.renderer, data: item.data })
        break
      default: {
        // 后端先上了新 item 类型时，宁可显示“暂不支持”，也不要整段静默丢失
        const unknown = item as { id?: string; type?: string }
        sources.push({
          kind: 'unsupported',
          id: String(unknown.id ?? sources.length),
          sourceKind: String(unknown.type ?? 'unknown'),
        })
        break
      }
    }
  }

  return { sources, error, compactions, interrupted }
}

export function liveSources(live: LiveRun): TurnSource[] {
  const sources: TurnSource[] = []
  for (const block of live.blocks) {
    switch (block.kind) {
      case 'reasoning':
        if (block.text) {
          sources.push({
            kind: 'reasoning',
            id: block.id,
            text: block.text,
            streaming: Boolean(block.streaming),
          })
        }
        break
      case 'tool':
        if (block.tool) sources.push({ kind: 'tool', step: liveToolStep(block.tool) })
        break
      case 'text':
        if (block.text) {
          sources.push({
            kind: 'text',
            id: block.id,
            text: block.text,
            streaming: Boolean(block.streaming),
          })
        }
        break
      case 'artifact':
        for (const media of block.media ?? []) {
          sources.push({ kind: 'media', media: mediaFromLive(media) })
        }
        break
      default: {
        // 前端先收到未知 block 时保留位置，别让整段流式内容凭空消失
        const unknown = block as { id?: string; kind?: string }
        sources.push({
          kind: 'unsupported',
          id: String(unknown.id ?? sources.length),
          sourceKind: String(unknown.kind ?? 'unknown'),
        })
        break
      }
    }
  }
  return sources
}

export function fillUser(view: TurnView, run: SessionRun): void {
  const text: string[] = []
  for (const item of run.content) {
    if (item.type === 'text' && item.role === 'user') text.push(item.text)
    else if (item.type === 'image' && item.role === 'user') view.userImages.push(item)
    else if (item.type === 'video' && item.role === 'user') view.userVideos.push(item)
    else if (item.type === 'resource' && item.role === 'user') view.userResources.push(item)
  }
  view.userText = text.join('\n\n')
}