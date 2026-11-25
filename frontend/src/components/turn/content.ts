import type { Component } from 'vue'
import type { RunStatus } from '@/types/api'
import type { TurnBlock } from '@/lib/turn/types'
import MarkdownMessage from '@/components/chat/MarkdownMessage.vue'
import ThinkingChain from '@/components/chat/ThinkingChain.vue'
import CustomCardBlock from './CustomCardBlock.vue'
import MediaBlock from './MediaBlock.vue'
import UnknownBlock from './UnknownBlock.vue'

/** 模板传给块渲染器的上下文；块自己不知道轮次、位置和展开偏好。 */
export interface BlockContext {
  isStreaming: boolean
  status: RunStatus | 'streaming'
  chainCount: number
  lastChainIndex: number
  chainStartedAt: string | null
  chainEndedAt: string | null
  defaultOpen: boolean
  defaultDetailsOpen: boolean
}

interface ContentRenderer {
  component: Component
  props: (block: TurnBlock, ctx: BlockContext) => Record<string, unknown>
}

const CONTENT: Record<TurnBlock['type'], ContentRenderer> = {
  text: {
    component: MarkdownMessage,
    props: (block, ctx) => (block.type === 'text'
      ? { content: block.text, streaming: ctx.isStreaming && block.streaming }
      : {}),
  },
  chain: {
    component: ThinkingChain,
    props: (block, ctx) => (block.type === 'chain'
      ? {
          chain: block.entries,
          isStreaming: ctx.isStreaming && block.streaming,
          status: ctx.isStreaming && !block.streaming ? 'completed' : ctx.status,
          startedAt: ctx.chainStartedAt,
          endedAt: ctx.chainEndedAt,
          defaultOpen: ctx.defaultOpen,
          defaultDetailsOpen: ctx.defaultDetailsOpen,
        }
      : {}),
  },
  media: {
    component: MediaBlock,
    props: (block) => (block.type === 'media'
      ? { media: block.media, state: block.state }
      : {}),
  },
  card: {
    component: CustomCardBlock,
    props: (block) => (block.type === 'card'
      ? { renderer: block.renderer, data: block.data }
      : {}),
  },
  unknown: {
    component: UnknownBlock,
    props: (block) => (block.type === 'unknown'
      ? { sourceKind: block.sourceKind }
      : {}),
  },
}

export function rendererFor(type: string): ContentRenderer {
  return CONTENT[type as TurnBlock['type']] ?? CONTENT.unknown
}