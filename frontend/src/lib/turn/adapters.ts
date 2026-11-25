import type { ToolStep } from '@/lib/tools'
import type { SourceRef, TurnPart, TurnSource } from './types'

interface SourceAdapter {
  match(source: TurnSource): boolean
  project(source: TurnSource): TurnPart[] | null
}

function collectSourceRefs(
  value: unknown,
  found: Map<string, SourceRef>,
  skip = false,
): void {
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
    for (const item of value) collectSourceRefs(item, found, skip)
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
    collectSourceRefs(item, found, key === 'site_icon')
  }
}

/** 工具结果里出现的链接统一收进来源区，具体工具不需要各自登记。 */
function sourceParts(value: unknown): TurnPart[] {
  const found = new Map<string, SourceRef>()
  collectSourceRefs(value, found)
  return [...found.values()].map(source => ({
    type: 'source-link' as const,
    id: `source:${source.url}`,
    source,
  }))
}

function stepParts(step: ToolStep): TurnPart[] {
  return [
    { type: 'chain-entry', id: `step-${step.id}`, entry: { kind: 'tool', step } },
    ...sourceParts(step.result),
  ]
}

const textAdapter: SourceAdapter = {
  match: source => source.kind === 'text',
  project: (source) => {
    if (source.kind !== 'text' || !source.text) return null
    return [{ type: 'text', id: source.id, text: source.text, streaming: source.streaming }]
  },
}

const reasoningAdapter: SourceAdapter = {
  match: source => source.kind === 'reasoning',
  project: (source) => {
    if (source.kind !== 'reasoning' || !source.text) return null
    return [{
      type: 'chain-entry',
      id: `reasoning-${source.id}`,
      entry: {
        kind: 'reasoning',
        id: source.id,
        text: source.text,
        streaming: source.streaming,
      },
    }]
  },
}

const mediaAdapter: SourceAdapter = {
  match: source => source.kind === 'media',
  project: (source) => {
    if (source.kind !== 'media') return null
    if (source.media.kind === 'file') {
      return [{ type: 'attachment', id: `file-${source.media.id}`, media: [source.media] }]
    }
    return [{
      type: 'media',
      id: `media-${source.media.id}`,
      media: [source.media],
      state: 'ready',
    }]
  },
}

const customAdapter: SourceAdapter = {
  match: source => source.kind === 'custom',
  project: (source) => {
    if (source.kind !== 'custom') return null
    return [{ type: 'card', id: `card-${source.id}`, renderer: source.renderer, data: source.data }]
  },
}

/** 出图成功时步骤本身就是噪音，占位和图片已经说明了进度。 */
const generateImageAdapter: SourceAdapter = {
  match: source => source.kind === 'tool' && source.step.name === 'generate_image',
  project: (source) => {
    if (source.kind !== 'tool') return null
    const { step } = source
    if (step.state === 'running' || step.state === 'waiting') {
      return [{ type: 'media', id: `pending-${step.id}`, media: [], state: 'pending' }]
    }
    if (step.state === 'failed' || step.state === 'interrupted') return stepParts(step)
    return sourceParts(step.result)
  },
}

const toolAdapter: SourceAdapter = {
  match: source => source.kind === 'tool',
  project: (source) => {
    if (source.kind !== 'tool') return null
    return stepParts(source.step)
  },
}

const unsupportedAdapter: SourceAdapter = {
  match: () => true,
  project: (source) => {
    const id = 'id' in source
      ? source.id
      : 'step' in source
        ? source.step.id
        : 'media' in source
          ? source.media.id
          : 'source'
    return [{ type: 'unknown', id: `unknown-${id}`, sourceKind: source.kind }]
  },
}

const ADAPTERS: SourceAdapter[] = [
  generateImageAdapter,
  toolAdapter,
  textAdapter,
  reasoningAdapter,
  mediaAdapter,
  customAdapter,
  unsupportedAdapter,
]

function fallbackParts(source: TurnSource): TurnPart[] {
  if (source.kind === 'tool') return stepParts(source.step)
  const id = 'id' in source
    ? source.id
    : 'media' in source
      ? source.media.id
      : 'source'
  return [{ type: 'unknown', id: `unknown-${id}`, sourceKind: source.kind }]
}

export function projectSource(source: TurnSource): TurnPart[] | null {
  try {
    const adapter = ADAPTERS.find(item => item.match(source))
    return adapter ? adapter.project(source) : fallbackParts(source)
  } catch (error) {
    // 单个适配器坏掉只降级这一条来源，不能把整条消息弄没
    console.error('Turn source adapter failed', { kind: source.kind, error })
    return fallbackParts(source)
  }
}