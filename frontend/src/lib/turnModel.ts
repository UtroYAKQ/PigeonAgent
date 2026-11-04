import type {
  CompactionItem,
  ErrorItem,
  FileItem,
  ImageItem,
  LiveMedia,
  LiveRun,
  ResourceItem,
  RunStatus,
  SessionRun,
  ToolResultItem,
  VideoItem,
} from '@/types/api'
import {
  buildToolSteps,
  liveToolStep,
  mediaKind,
  planFromSteps,
  toolLabel,
  type PlanState,
  type ToolState,
  type ToolStep,
} from './tools'

export interface ReasoningEntry {
  kind: 'reasoning'
  id: string
  text: string
  streaming: boolean
}

export interface ToolEntry {
  kind: 'tool'
  step: ToolStep
}

export type ChainEntry = ReasoningEntry | ToolEntry

export interface ChainSegment {
  kind: 'chain'
  id: string
  entries: ChainEntry[]
  streaming: boolean
}

export interface TextSegment {
  kind: 'text'
  id: string
  text: string
  streaming: boolean
}

/** 产物在正文里的统一形态；图片、视频、附件都走这一层，渲染侧不用分辨来源 */
export interface ArtifactMedia {
  id: string
  kind: 'image' | 'video' | 'file'
  /** generated = 图片工具产出；workspace = 沙箱里写的文件 */
  origin: 'generated' | 'workspace'
  mediaType: string
  fileId?: string | null
  src?: string | null
  data?: string | null
  name?: string
  size?: number
  alt?: string | null
}

export interface ArtifactSegment {
  kind: 'artifact'
  id: string
  media: ArtifactMedia[]
  /** 计费接入前先留空 */
  credits: number | null
}

export type TurnSegment = ChainSegment | TextSegment | ArtifactSegment

export interface SourceRef {
  url: string
  icon: string | null
}

export interface TurnView {
  userText: string
  userImages: ImageItem[]
  userVideos: VideoItem[]
  userResources: ResourceItem[]
  userFiles: FileItem[]
  assistantText: string
  segments: TurnSegment[]
  steps: ToolStep[]
  plan: PlanState | null
  compactions: CompactionItem[]
  error: ErrorItem | null
  liveError: string | null
  liveErrorCode: string | null
  /** 工作区发布的非视觉文件；不进正文，统一在回合末尾列出 */
  attachments: ArtifactMedia[]
  /** 有出图任务正在跑；用来渲染占位骨架而不是链里的步骤 */
  generatingImage: boolean
  status: RunStatus | 'streaming'
  interrupted: boolean
  cancelled: boolean
  sources: SourceRef[]
}

function emptyView(): TurnView {
  return {
    userText: '',
    userImages: [],
    userVideos: [],
    userResources: [],
    userFiles: [],
    assistantText: '',
    segments: [],
    steps: [],
    plan: null,
    compactions: [],
    attachments: [],
    error: null,
    liveError: null,
    liveErrorCode: null,
    generatingImage: false,
    status: 'completed',
    interrupted: false,
    cancelled: false,
    sources: [],
  }
}

interface SegmentState {
  segments: TurnSegment[]
  chain: ChainSegment | null
  text: TextSegment | null
}

function createSegmentState(): SegmentState {
  return { segments: [], chain: null, text: null }
}

/**
 * 段 id 会在 v-for 里当 key 用，同一条视图里必须唯一。
 * 出图后模型常会带着同一个 messageId 继续思考（正文也一样），
 * 直接复用 `chain-${id}` 就会和前面那段撞 key —— Vue 一撞就把夹在中间的产物卡挤掉。
 */
function uniqueSegmentId(state: SegmentState, base: string): string {
  const taken = new Set(state.segments.map(segment => segment.id))
  if (!taken.has(base)) return base
  let suffix = 2
  while (taken.has(`${base}#${suffix}`)) suffix += 1
  return `${base}#${suffix}`
}

function appendChainEntry(state: SegmentState, entry: ChainEntry): void {
  if (state.chain) {
    state.chain.entries.push(entry)
    return
  }
  const key = entry.kind === 'reasoning' ? entry.id : entry.step.id
  const segment: ChainSegment = {
    kind: 'chain',
    id: uniqueSegmentId(state, `chain-${key}`),
    entries: [entry],
    streaming: false,
  }
  state.segments.push(segment)
  state.chain = segment
  state.text = null
}

function appendAssistantText(state: SegmentState, id: string, text: string): void {
  if (!text) return
  if (state.text) {
    state.text.text = state.text.text ? `${state.text.text}\n\n${text}` : text
    return
  }
  const segment: TextSegment = {
    kind: 'text',
    id: uniqueSegmentId(state, `text-${id}`),
    text,
    streaming: false,
  }
  state.segments.push(segment)
  state.text = segment
  state.chain = null
}

/**
 * 产物单独成段：它和正文、思维链是三种并列的输出形态。
 *
 * 断段点从「正文」扩成「正文 + 产物」之后，工具并行也不会错位——图出现在
 * 它被生成的那一帧，后面的步骤自然接到新的链段里。连续到达的产物并进同一段，
 * 一次生成 4 张就是一张 2×2 网格，不会拆成 4 段。
 */
function appendArtifact(state: SegmentState, media: ArtifactMedia[]): void {
  if (!media.length) return
  const last = state.segments[state.segments.length - 1]
  if (last?.kind === 'artifact') {
    last.media.push(...media)
    return
  }
  state.segments.push({
    kind: 'artifact',
    id: uniqueSegmentId(state, `artifact-${media[0].id}`),
    media: [...media],
    credits: null,
  })
  state.chain = null
  state.text = null
}

/** 文件类产物不进正文，避免和末尾清单重复两遍 */
function collectArtifacts(state: SegmentState, view: TurnView, media: ArtifactMedia[]): void {
  const visuals = media.filter(item => item.kind !== 'file')
  const files = media.filter(item => item.kind === 'file')
  if (visuals.length) appendArtifact(state, visuals)
  if (files.length) view.attachments.push(...files)
}

function mediaFromItem(item: ImageItem | VideoItem | ResourceItem | FileItem): ArtifactMedia {
  if (item.type === 'resource') {
    // 工作区发布的图也要预览出来，否则用户分不清自己拿到的是什么
    return {
      id: item.id,
      kind: mediaKind(item.media_type),
      origin: 'workspace',
      mediaType: item.media_type,
      fileId: item.storage_key,
      name: item.name,
      size: item.size,
    }
  }
  if (item.type === 'file') {
    return {
      id: item.id,
      kind: mediaKind(item.media_type),
      origin: 'workspace',
      mediaType: item.media_type,
      data: item.data,
      name: item.name,
      size: item.size,
    }
  }
  return {
    id: item.id,
    kind: item.type === 'video' ? 'video' : 'image',
    origin: 'generated',
    mediaType: item.media_type ?? (item.type === 'video' ? 'video/mp4' : 'image/png'),
    fileId: item.file_id,
    src: item.url,
    data: item.data,
    alt: item.alt,
  }
}

function mediaFromLive(media: LiveMedia): ArtifactMedia {
  return {
    id: media.file_id,
    kind: mediaKind(media.media_type),
    origin: media.origin === 'workspace' ? 'workspace' : 'generated',
    mediaType: media.media_type,
    fileId: media.file_id,
    name: media.name,
    size: media.size,
    alt: media.alt,
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
    kind: 'turn',
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

/**
 * 出图步骤不进思维链。
 *
 * 图片本身就是最好的进度反馈，链里再挂一条「图片已生成 xxx」纯属噪音；
 * 只有失败或被打断时才需要它——那时用户得知道为什么没有图。
 */
function hidesToolStep(step: ToolStep): boolean {
  if (step.name !== 'generate_image') return false
  return step.state !== 'failed' && step.state !== 'interrupted'
}

function assistantTextOf(segments: TurnSegment[]): string {
  return segments
    .flatMap(segment => (segment.kind === 'text' ? [segment.text] : []))
    .filter(Boolean)
    .join('\n\n')
}

function stepsOf(segments: TurnSegment[]): ToolStep[] {
  return segments.flatMap(segment => (
    segment.kind === 'chain'
      ? segment.entries.flatMap(entry => (entry.kind === 'tool' ? [entry.step] : []))
      : []
  ))
}

function fillUser(view: TurnView, run: SessionRun): void {
  const text: string[] = []
  for (const item of run.content) {
    if (item.type === 'text' && item.role === 'user') text.push(item.text)
    else if (item.type === 'image' && item.role === 'user') view.userImages.push(item)
    else if (item.type === 'video' && item.role === 'user') view.userVideos.push(item)
    else if (item.type === 'resource' && item.role === 'user') view.userResources.push(item)
    else if (item.type === 'file' && item.role === 'user') view.userFiles.push(item)
  }
  view.userText = text.join('\n\n')
}

/** 搜索结果自带站点图标；其余工具里出现的链接只有 URL，用默认地球图标兜底。 */
function collectSources(value: unknown, found: Map<string, SourceRef>, skip = false): void {
  if (typeof value === 'string') {
    if (skip) return
    const matches = value.match(/https?:\/\/[^\s"'<>)\]]+/g) ?? []
    for (const match of matches) {
      const url = match.replace(/[.,;]+$/, '')
      if (!found.has(url)) found.set(url, { url, icon: null })
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectSources(item, found, skip)
    return
  }
  if (!value || typeof value !== 'object') return

  const record = value as Record<string, unknown>
  const url = typeof record.url === 'string' ? record.url.trim() : ''
  const icon = typeof record.site_icon === 'string' && /^https?:\/\//.test(record.site_icon)
    ? record.site_icon
    : null
  if (url && icon) {
    const existing = found.get(url)
    if (existing) existing.icon = icon
    else found.set(url, { url, icon })
  }
  for (const [key, item] of Object.entries(record)) {
    collectSources(item, found, key === 'site_icon')
  }
}

function mergeSources(base: SourceRef[], live: SourceRef[]): SourceRef[] {
  const merged = new Map<string, SourceRef>()
  for (const source of [...base, ...live]) {
    const existing = merged.get(source.url)
    if (!existing || (!existing.icon && source.icon)) merged.set(source.url, source)
  }
  return [...merged.values()]
}

/** 正文、步骤、计划、来源全部从同一批段落算出来；流式分支和历史分支的收尾一模一样。 */
function settleAssistant(view: TurnView, state: SegmentState, steps: ToolStep[]): void {
  const sources = new Map<string, SourceRef>()
  for (const step of steps) {
    collectSources(step.result, sources)
  }
  view.segments = state.segments
  view.assistantText = assistantTextOf(state.segments)
  view.steps = steps
  view.plan = planFromSteps(steps)
  view.sources = [...sources.values()].slice(0, 6)
}

/** 出图步骤不进思维链，所以它跑没跑完只能回到原始工具状态判断 */
function isPendingImage(name: string, state: ToolState): boolean {
  return name === 'generate_image' && (state === 'running' || state === 'waiting')
}

/** 这一轮还在流式：块就是最新事实，落库的 content 反而落后一拍。 */
function buildLiveView(view: TurnView, live: LiveRun): TurnView {
  view.status = 'streaming'
  view.liveError = live.error
  view.liveErrorCode = live.errorCode ?? null
  const state = createSegmentState()

  for (const block of live.blocks) {
    if (block.kind === 'reasoning' && block.text) {
      appendChainEntry(state, {
        kind: 'reasoning',
        id: block.id,
        text: block.text,
        streaming: Boolean(block.streaming),
      })
    } else if (block.kind === 'tool' && block.tool) {
      const step = liveToolStep(block.tool)
      if (!hidesToolStep(step)) appendChainEntry(state, { kind: 'tool', step })
    } else if (block.kind === 'text' && block.text) {
      appendAssistantText(state, block.id, block.text)
    } else if (block.kind === 'artifact' && block.media?.length) {
      collectArtifacts(state, view, block.media.map(mediaFromLive))
    }
  }

  if (!live.finished) {
    const last = state.segments[state.segments.length - 1]
    if (last && last.kind !== 'artifact') last.streaming = true
  }

  // 链里看不到出图步骤，所以进度改由占位骨架表达
  view.generatingImage = live.blocks.some(block => (
    block.kind === 'tool' && block.tool !== undefined
    && isPendingImage(block.tool.name, block.tool.state)
  ))
  settleAssistant(view, state, stepsOf(state.segments))
  return view
}

/** 这一轮已经落库：run.content 是唯一的结构化来源。 */
function buildHistoryView(
  view: TurnView,
  run: SessionRun,
  externalResults?: Map<string, ToolResultItem>,
): TurnView {
  let interrupted = run.status === 'interrupted'
  let steps = buildToolSteps(run.content, externalResults)
  if (run.status !== 'running') {
    // 已经结束的 run 里没有结果的工具不会继续执行；别让 UI 一直停留在“正在…”。
    // completed/failed 的 run 缺 result 属于数据异常，显示失败回执；
    // cancelled/interrupted 才是真正的“没有跑完”。
    const finished = run.status === 'completed' || run.status === 'failed'
    const fallback = finished ? ('failed' as const) : ('interrupted' as const)
    steps = steps.map(step => (step.result
      ? step
      : { ...step, state: fallback, label: toolLabel(step.name, fallback) }))
  }
  const stepById = new Map(steps.map(step => [step.id, step]))
  const usedSteps = new Set<string>()
  const state = createSegmentState()

  for (const item of run.content) {
    if (item.display === false) continue
    switch (item.type) {
      case 'text':
        if (item.role === 'assistant') appendAssistantText(state, item.id, item.text)
        break
      case 'thinking':
        if (item.text) {
          appendChainEntry(state, {
            kind: 'reasoning',
            id: item.id,
            text: item.text,
            streaming: false,
          })
        }
        break
      case 'tool_call': {
        const step = stepById.get(item.tool_call_id)
        if (step && !usedSteps.has(step.id)) {
          usedSteps.add(step.id)
          if (!hidesToolStep(step)) appendChainEntry(state, { kind: 'tool', step })
        }
        break
      }
      case 'tool_result':
        break
      case 'image':
        if (item.role === 'assistant') appendArtifact(state, [mediaFromItem(item)])
        break
      case 'video':
        if (item.role === 'assistant') appendArtifact(state, [mediaFromItem(item)])
        break
      case 'resource':
        if (item.role === 'assistant') collectArtifacts(state, view, [mediaFromItem(item)])
        break
      case 'file':
        if (item.role === 'assistant') collectArtifacts(state, view, [mediaFromItem(item)])
        break
      case 'error':
        view.error = item
        break
      case 'approval_request':
      case 'call_request':
        interrupted = true
        break
      case 'compaction':
        view.compactions.push(item)
        break
      default:
        break
    }
  }

  view.generatingImage = run.status === 'running' && steps.some(step => isPendingImage(step.name, step.state))
  view.interrupted = interrupted
  view.cancelled = run.status === 'cancelled'
  settleAssistant(view, state, steps)
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

function mergeSegments(base: TurnSegment[], live: TurnSegment[]): TurnSegment[] {
  const merged = [...base]
  const tail = merged[merged.length - 1]
  const head = live[0]
  if (tail?.kind === 'chain' && head?.kind === 'chain') {
    merged[merged.length - 1] = {
      ...tail,
      entries: [...tail.entries, ...head.entries],
      streaming: head.streaming,
    }
    merged.push(...live.slice(1))
  } else if (tail?.kind === 'text' && head?.kind === 'text') {
    merged[merged.length - 1] = {
      ...tail,
      text: [tail.text, head.text].filter(Boolean).join('\n\n'),
      streaming: head.streaming,
    }
    merged.push(...live.slice(1))
  } else if (tail?.kind === 'artifact' && head?.kind === 'artifact') {
    merged[merged.length - 1] = {
      ...tail,
      media: [...tail.media, ...head.media],
    }
    merged.push(...live.slice(1))
  } else {
    merged.push(...live)
  }
  return merged
}

export function mergeTurnViews(base: TurnView | null, live: TurnView): TurnView {
  if (!base) return live
  const segments = mergeSegments(base.segments, live.segments)
  const steps = [...base.steps, ...live.steps]
  return {
    ...live,
    userText: [base.userText, live.userText].filter(Boolean).join('\n\n'),
    userImages: [...base.userImages, ...live.userImages],
    userVideos: [...base.userVideos, ...live.userVideos],
    userResources: [...base.userResources, ...live.userResources],
    userFiles: [...base.userFiles, ...live.userFiles],
    assistantText: assistantTextOf(segments),
    segments,
    steps,
    plan: planFromSteps(steps),
    compactions: [...base.compactions, ...live.compactions],
    attachments: [...base.attachments, ...live.attachments],
    error: live.error ?? base.error,
    status: 'streaming',
    interrupted: false,
    cancelled: false,
    sources: mergeSources(base.sources, live.sources).slice(0, 6),
  }
}

export function hasAssistantOutput(view: TurnView): boolean {
  // 产物已经是 segment 的一种，不需要再单独判断
  return Boolean(view.segments.length || view.attachments.length || view.error || view.liveError)
}

export function hasUserOutput(view: TurnView): boolean {
  return Boolean(
    view.userText
    || view.userImages.length
    || view.userVideos.length
    || view.userResources.length
    || view.userFiles.length,
  )
}
