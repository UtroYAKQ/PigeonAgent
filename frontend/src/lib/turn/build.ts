import type { LiveRun, SessionRun, ToolResultItem } from '@/types/api'
import { toolLabel, type ToolStep } from '@/lib/tools'
import type {
  ArtifactMedia,
  ChainBlock,
  ChainEntry,
  MediaBlock,
  SourceRef,
  TextBlock,
  TurnBlock,
  TurnPart,
  TurnSource,
  TurnView,
} from './types'
import { projectSource } from './adapters'
import { fillUser, historySources, liveSources } from './sources'

function emptyView(): TurnView {
  return {
    userText: '',
    userImages: [],
    userVideos: [],
    userResources: [],
    blocks: [],
    steps: [],
    compactions: [],
    liveCompaction: null,
    error: null,
    liveError: null,
    liveErrorCode: null,
    attachments: [],
    assistantText: '',
    status: 'completed',
    interrupted: false,
    cancelled: false,
    sources: [],
  }
}

function uniqueBlockId(used: Set<string>, base: string): string {
  if (!used.has(base)) {
    used.add(base)
    return base
  }
  let suffix = 2
  while (used.has(`${base}#${suffix}`)) suffix += 1
  const id = `${base}#${suffix}`
  used.add(id)
  return id
}

/**
 * Part 流按正文顺序聚成块：连续的文字、链条目、媒体各并一段；
 * 来源和附件是 footer 内容，不参与正文分段。
 */
function groupParts(parts: TurnPart[]): TurnBlock[] {
  const blocks: TurnBlock[] = []
  const used = new Set<string>()
  let chain: ChainBlock | null = null
  let text: TextBlock | null = null
  let media: MediaBlock | null = null

  function reset(): void {
    chain = null
    text = null
    media = null
  }

  for (const part of parts) {
    if (part.type === 'text') {
      if (text) {
        text.text = text.text ? `${text.text}\n\n${part.text}` : part.text
        continue
      }
      text = {
        type: 'text',
        id: uniqueBlockId(used, `text-${part.id}`),
        text: part.text,
        streaming: false,
      }
      blocks.push(text)
      chain = null
      media = null
      continue
    }

    if (part.type === 'chain-entry') {
      if (chain) {
        chain.entries.push(part.entry)
        continue
      }
      const key = part.entry.kind === 'reasoning' ? part.entry.id : part.entry.step.id
      chain = {
        type: 'chain',
        id: uniqueBlockId(used, `chain-${key}`),
        entries: [part.entry],
        streaming: false,
      }
      blocks.push(chain)
      text = null
      media = null
      continue
    }

    if (part.type === 'media') {
      if (media) {
        media.media.push(...part.media)
        if (media.media.length) media.state = 'ready'
        continue
      }
      media = {
        type: 'media',
        id: uniqueBlockId(used, part.id),
        media: [...part.media],
        state: part.state,
      }
      blocks.push(media)
      chain = null
      text = null
      continue
    }

    if (part.type === 'card' || part.type === 'unknown') {
      blocks.push({
        ...part,
        id: uniqueBlockId(used, part.id),
      })
      reset()
    }
  }

  return blocks
}

function collectSources(parts: TurnPart[]): SourceRef[] {
  const merged = new Map<string, SourceRef>()
  for (const part of parts) {
    if (part.type !== 'source-link') continue
    const existing = merged.get(part.source.url)
    if (!existing || (!existing.icon && part.source.icon)) {
      merged.set(part.source.url, part.source)
    }
  }
  return [...merged.values()].slice(0, 6)
}

function collectAttachments(parts: TurnPart[]): ArtifactMedia[] {
  return parts.flatMap(part => (part.type === 'attachment' ? part.media : []))
}

function sourceSteps(sources: TurnSource[]): ToolStep[] {
  return sources.flatMap(source => (source.kind === 'tool' ? [source.step] : []))
}

function assistantTextOf(blocks: TurnBlock[]): string {
  return blocks
    .flatMap(block => (block.type === 'text' ? [block.text] : []))
    .filter(Boolean)
    .join('\n\n')
}

function settle(view: TurnView, parts: TurnPart[], steps: ToolStep[]): void {
  const blocks = groupParts(parts)
  view.blocks = blocks
  view.sources = collectSources(parts)
  view.attachments = collectAttachments(parts)
  // steps 保留所有工具（包括被正文隐藏的出图步骤），续写合并和来源判断都要用
  view.steps = steps
  view.assistantText = assistantTextOf(blocks)
}

function markLastStreaming(blocks: TurnBlock[]): void {
  const last = blocks[blocks.length - 1]
  if (last && (last.type === 'text' || last.type === 'chain')) last.streaming = true
}

function buildHistoryView(
  view: TurnView,
  run: SessionRun,
  externalResults?: Map<string, ToolResultItem>,
): TurnView {
  const info = historySources(run, externalResults)
  view.status = run.status
  view.error = info.error
  view.compactions = info.compactions
  view.interrupted = info.interrupted
  view.cancelled = run.status === 'cancelled'
  const parts = info.sources.flatMap(source => projectSource(source) ?? [])
  settle(view, parts, sourceSteps(info.sources))
  return view
}

/** 这一轮还在流式：块就是最新事实，落库的 content 反而落后一拍。 */
function buildLiveView(view: TurnView, live: LiveRun): TurnView {
  // RUN_FINISHED 一到就收掉流式态：后端收尾可能还要几秒，不能让转圈一直等到连接结束
  view.status = live.finished ? (live.error ? 'failed' : 'completed') : 'streaming'
  view.liveError = live.error
  view.liveErrorCode = live.errorCode ?? null
  view.liveCompaction = live.compaction
  const sources = liveSources(live)
  const parts = sources.flatMap(source => projectSource(source) ?? [])
  settle(view, parts, sourceSteps(sources))
  if (!live.finished) markLastStreaming(view.blocks)
  return view
}

export function buildTurnView(
  run: SessionRun,
  live: LiveRun | null,
  externalResults?: Map<string, ToolResultItem>,
): TurnView {
  const view = emptyView()
  fillUser(view, run)
  view.status = run.status
  if (live && live.runId === run.id) return buildLiveView(view, live)
  return buildHistoryView(view, run, externalResults)
}

/** 同一次工具调用的结果在续写段里又出现时，保留原位置、用实时结果覆盖旧状态。 */
function mergeChainEntries(
  base: ChainEntry[],
  live: ChainEntry[],
  stepById: Map<string, ToolStep>,
): ChainEntry[] {
  const entries = [...base]
  const indexById = new Map<string, number>()
  entries.forEach((entry, index) => {
    if (entry.kind === 'tool') indexById.set(entry.step.id, index)
  })
  for (const entry of live) {
    if (entry.kind !== 'tool') {
      entries.push(entry)
      continue
    }
    const step = stepById.get(entry.step.id) ?? entry.step
    const index = indexById.get(entry.step.id)
    if (index === undefined) {
      indexById.set(entry.step.id, entries.length)
      entries.push({ kind: 'tool', step })
    } else {
      entries[index] = { kind: 'tool', step }
    }
  }
  return entries
}

function mergeBlocks(
  base: TurnBlock[],
  live: TurnBlock[],
  stepById: Map<string, ToolStep>,
): TurnBlock[] {
  if (!base.length) return [...live]
  if (!live.length) return [...base]
  const merged = [...base]
  const tail = merged[merged.length - 1]
  const head = live[0]

  if (tail?.type === 'chain' && head?.type === 'chain') {
    merged[merged.length - 1] = {
      ...tail,
      entries: mergeChainEntries(tail.entries, head.entries, stepById),
      streaming: head.streaming,
    }
    merged.push(...live.slice(1))
  } else if (tail?.type === 'text' && head?.type === 'text') {
    merged[merged.length - 1] = {
      ...tail,
      text: [tail.text, head.text].filter(Boolean).join('\n\n'),
      streaming: head.streaming,
    }
    merged.push(...live.slice(1))
  } else if (tail?.type === 'media' && head?.type === 'media') {
    const media = [...tail.media, ...head.media]
    merged[merged.length - 1] = { ...tail, media, state: media.length ? 'ready' : head.state }
    merged.push(...live.slice(1))
  } else {
    merged.push(...live)
  }
  return merged
}

function mergeToolSteps(baseSteps: ToolStep[], liveSteps: ToolStep[]): ToolStep[] {
  const byId = new Map(baseSteps.map(step => [step.id, step]))
  for (const step of liveSteps) {
    const existing = byId.get(step.id)
    if (!existing) {
      byId.set(step.id, step)
      continue
    }
    const state = step.state === 'running' || step.state === 'waiting' ? existing.state : step.state
    byId.set(step.id, {
      ...existing,
      result: step.result ?? existing.result,
      outcome: step.outcome ?? existing.outcome,
      state,
      label: toolLabel(existing.name, state),
    })
  }
  return [...byId.values()]
}

function mergeSources(base: SourceRef[], live: SourceRef[]): SourceRef[] {
  const merged = new Map<string, SourceRef>()
  for (const source of [...base, ...live]) {
    const existing = merged.get(source.url)
    if (!existing || (!existing.icon && source.icon)) merged.set(source.url, source)
  }
  return [...merged.values()].slice(0, 6)
}

export function mergeTurnViews(base: TurnView | null, live: TurnView): TurnView {
  if (!base) return live
  const steps = mergeToolSteps(base.steps, live.steps)
  const stepById = new Map(steps.map(step => [step.id, step]))
  const blocks = mergeBlocks(base.blocks, live.blocks, stepById)
  return {
    ...live,
    userText: [base.userText, live.userText].filter(Boolean).join('\n\n'),
    userImages: [...base.userImages, ...live.userImages],
    userVideos: [...base.userVideos, ...live.userVideos],
    userResources: [...base.userResources, ...live.userResources],
    blocks,
    assistantText: assistantTextOf(blocks),
    steps,
    compactions: [...base.compactions, ...live.compactions],
    liveCompaction: live.liveCompaction ?? base.liveCompaction,
    attachments: [...base.attachments, ...live.attachments],
    error: live.error ?? base.error,
    status: live.status,
    interrupted: false,
    cancelled: false,
    sources: mergeSources(base.sources, live.sources),
  }
}

/**
 * 本轮还在生成、库里还没有这条 run 时，把它投影成一条 SessionRun 好让时间线渲染。
 * 用量还没有事件可取时给一份全零，视图不必自己编默认值。
 */
export function projectLiveRun(runs: SessionRun[], live: LiveRun | null): SessionRun | null {
  if (!live || runs.some(run => run.id === live.runId)) return null
  const now = new Date().toISOString()
  return {
    id: live.runId,
    session_id: live.sessionId,
    parent_run_id: null,
    seq: runs.length + 1,
    status: 'running',
    content: [],
    preview: '',
    usage: live.usage ?? {
      requests: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      total_tokens: 0,
    },
    compacted: false,
    branch: null,
    created_at: now,
    updated_at: now,
  }
}

export function hasAssistantOutput(view: TurnView): boolean {
  return Boolean(
    view.blocks.some(block => block.type !== 'media' || block.media.length > 0)
    || view.attachments.length
    || view.error
    || view.liveError,
  )
}

export function hasUserOutput(view: TurnView): boolean {
  return Boolean(
    view.userText
    || view.userImages.length
    || view.userVideos.length
    || view.userResources.length,
  )
}