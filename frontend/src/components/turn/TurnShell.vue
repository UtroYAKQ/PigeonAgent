<script setup lang="ts">
import { computed } from 'vue'
import { toast } from 'vue-sonner'
import { AlertTriangle, CircleSlash } from '@lucide/vue'

import AssistantActions from '@/components/chat/AssistantActions.vue'
import ContextCheckpoint from '@/components/chat/ContextCheckpoint.vue'
import FlightLoader from '@/components/chat/FlightLoader.vue'
import PendingBatchCard from '@/components/chat/PendingBatchCard.vue'
import SourcesRow from '@/components/chat/SourcesRow.vue'
import TurnFiles from '@/components/chat/TurnFiles.vue'
import { errorMessage } from '@/lib/http'
import type { PendingBatch } from '@/lib/pending'
import { hasAssistantOutput } from '@/lib/turn/build'
import type { TurnView } from '@/lib/turn/types'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import type { SessionRun } from '@/types/api'
import BlockBoundary from './BlockBoundary.vue'
import { rendererFor, type BlockContext } from './content'

const props = withDefaults(defineProps<{
  run: SessionRun
  view: TurnView
  mode?: 'chat' | 'readonly'
  isLast?: boolean
  hasBatch?: boolean
  hasPendingBatch?: boolean
  hideActions?: boolean
  showUser?: boolean
  interactions?: PendingBatch[]
}>(), {
  mode: 'chat',
  isLast: false,
  hasBatch: false,
  hasPendingBatch: false,
  hideActions: false,
  showUser: false,
  interactions: () => [],
})

const chat = useChatStore()
const ui = useUiStore()

const isChat = computed(() => props.mode === 'chat')
const isStreaming = computed(() => props.view.status === 'streaming')
const hasOutput = computed(() => hasAssistantOutput(props.view))
const displayText = computed(() => props.view.assistantText.trim())

const lastChainIndex = computed(() => {
  for (let index = props.view.blocks.length - 1; index >= 0; index -= 1) {
    if (props.view.blocks[index]?.type === 'chain') return index
  }
  return -1
})
const chainCount = computed(() => (
  props.view.blocks.filter(block => block.type === 'chain').length
))

const ERROR_TITLES: Record<string, string> = {
  quota_exceeded: '模型额度不足',
  rate_limited: '请求过于频繁',
  model_overloaded: '模型服务繁忙',
  model_unavailable: '模型不可用',
  model_timeout: '响应超时',
  model_connection: '连接失败',
  model_server_error: '模型服务错误',
  model_auth_error: '模型凭证无效',
  model_api_error: '模型调用失败',
  invalid_request: '请求被拒绝',
  context_window_exceeded: '上下文超限',
  content_filter: '内容被拦截',
  usage_limit_exceeded: '调用次数超限',
  tool_arguments_incomplete: '工具调用失败',
  unexpected_model_behavior: '生成结果异常',
  credits_exhausted: '积分已用尽',
}

const errorText = computed(() => props.view.liveError || props.view.error?.message || null)
const errorTitle = computed(() => {
  const code = props.view.error?.code ?? props.view.liveErrorCode
  return (code && ERROR_TITLES[code]) || '生成失败'
})
// 认证、额度、上下文超限这类错误原样重试不会成功，先不给重试入口
const errorRetryable = computed(() => props.view.error?.retryable !== false)
const errorRetryVisible = computed(() => (
  isChat.value && props.isLast && !chat.busy && errorRetryable.value
))

const note = computed(() => {
  if (props.view.interrupted) {
    if (props.hasBatch) return null
    if (!isChat.value) return hasOutput.value ? null : '这一轮没有返回可展示的内容。'
    return '这一轮需要人工确认或外部结果，当前版本暂不提供继续操作；已产生的内容保留在过程中。'
  }
  if (props.view.cancelled) return '生成已停止。'
  if (props.view.status === 'failed' && !errorText.value) {
    return isChat.value ? '生成中断，可以重试。' : '生成中断。'
  }
  if (!hasOutput.value && !isStreaming.value) {
    if (props.hasBatch) return null
    return '本轮没有返回可展示的内容。'
  }
  return null
})

const canRetryFromNote = computed(() => (
  isChat.value
  && props.view.status === 'failed'
  && !errorText.value
  && props.isLast
  && !chat.busy
))

function blockContext(index: number): BlockContext {
  return {
    isStreaming: isStreaming.value,
    status: props.view.status,
    chainCount: chainCount.value,
    lastChainIndex: lastChainIndex.value,
    chainStartedAt: isChat.value && chainCount.value === 1 && index === lastChainIndex.value
      ? props.run.created_at
      : null,
    chainEndedAt: isChat.value && chainCount.value === 1 && !isStreaming.value
      ? props.run.updated_at
      : null,
    defaultOpen: ui.autoExpandThinking || (isChat.value && props.isLast && index === lastChainIndex.value),
    defaultDetailsOpen: ui.autoExpandToolDetails,
  }
}

const renderedBlocks = computed(() => props.view.blocks.map((block, index) => {
  const renderer = rendererFor(block.type)
  return {
    key: block.id,
    component: renderer.component,
    props: renderer.props(block, blockContext(index)),
  }
}))

async function retry(): Promise<void> {
  try {
    await chat.regenerate(props.run)
  } catch (error) {
    toast.error('重试失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <article class="flex min-w-0 flex-col gap-4">
    <ContextCheckpoint
      v-if="view.liveCompaction"
      :state="view.liveCompaction.status"
      :summary="view.liveCompaction.summary"
      :tokens-before="view.liveCompaction.tokensBefore"
    />
    <ContextCheckpoint
      v-for="item in view.compactions"
      :key="item.id"
      state="done"
      :summary="item.summary"
      :tokens-before="item.tokens_before || null"
    />

    <slot name="user" />
    <div v-if="mode === 'readonly' && showUser && view.userText" class="ml-auto max-w-[85%]">
      <div class="rounded-2xl bg-surface px-4 py-3 text-[14px] leading-7 whitespace-pre-wrap break-words">
        {{ view.userText }}
      </div>
    </div>

    <div class="min-w-0">
      <BlockBoundary v-for="item in renderedBlocks" :key="item.key">
        <component :is="item.component" v-bind="item.props" />
      </BlockBoundary>

      <TurnFiles
        v-if="view.attachments.length && (!isChat || !isStreaming)"
        :media="view.attachments"
      />

      <FlightLoader v-if="isChat && isStreaming" class="mt-4" />

      <div
        v-if="errorText"
        class="mt-4 rounded-xl border border-destructive/20 bg-destructive/[0.04] px-4 py-3"
      >
        <div class="flex items-center gap-2">
          <AlertTriangle class="size-3.5 shrink-0 text-destructive" />
          <span class="text-[12.5px] font-medium text-destructive">{{ errorTitle }}</span>
          <button
            v-if="errorRetryVisible"
            type="button"
            class="ml-auto rounded-full border border-destructive/25 px-2.5 py-0.5 text-[11.5px] text-destructive transition-colors hover:bg-destructive/10"
            @click="retry"
          >
            重试
          </button>
        </div>
        <p class="mt-1.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-words font-mono text-[11.5px] leading-5 text-muted-foreground">
          {{ errorText }}
        </p>
      </div>

      <div v-else-if="note" class="mt-4 flex items-start gap-2 text-[12px] leading-5 text-muted-foreground">
        <CircleSlash v-if="view.interrupted" class="mt-0.5 size-3.5 shrink-0" />
        <AlertTriangle v-else-if="canRetryFromNote" class="mt-0.5 size-3.5 shrink-0 text-destructive" />
        <span class="min-w-0 flex-1" :class="canRetryFromNote ? 'text-destructive' : ''">{{ note }}</span>
        <button
          v-if="canRetryFromNote"
          type="button"
          class="shrink-0 rounded-full border border-destructive/25 px-2.5 py-0.5 text-[11.5px] text-destructive transition-colors hover:bg-destructive/10"
          @click="retry"
        >
          重试
        </button>
      </div>

      <SourcesRow
        v-if="view.sources.length && (!isChat || (!isStreaming && !hasPendingBatch && !chat.busy))"
        :sources="view.sources"
      />

      <PendingBatchCard
        v-for="batch in interactions"
        :key="batch.interruptId"
        :batch="batch"
      />

      <AssistantActions
        v-if="isChat && !isStreaming && !hideActions"
        :run="run"
        :content="displayText"
        :usage="run.usage"
        :is-last="isLast"
        :is-streaming="isStreaming"
      />
    </div>
  </article>
</template>