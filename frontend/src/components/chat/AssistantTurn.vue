<script setup lang="ts">
import { computed } from 'vue'
import { toast } from 'vue-sonner'
import { AlertTriangle, CircleSlash } from '@lucide/vue'

import { errorMessage } from '@/lib/http'
import { hasAssistantOutput, type TurnView } from '@/lib/turnModel'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import type { SessionRun } from '@/types/api'
import AssistantActions from './AssistantActions.vue'
import ArtifactBlock from './ArtifactBlock.vue'
import ArtifactSkeleton from './ArtifactSkeleton.vue'
import FlightLoader from './FlightLoader.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import SourcesRow from './SourcesRow.vue'
import TurnFiles from './TurnFiles.vue'
import ThinkingChain from './ThinkingChain.vue'

const props = defineProps<{
  run: SessionRun
  view: TurnView
  isLast: boolean
  hasBatch?: boolean
  hideActions?: boolean
}>()

const chat = useChatStore()
const ui = useUiStore()

const isStreaming = computed(() => props.view.status === 'streaming')
const lastChainIndex = computed(() => {
  for (let index = props.view.segments.length - 1; index >= 0; index -= 1) {
    if (props.view.segments[index]?.kind === 'chain') return index
  }
  return -1
})
const chainCount = computed(() => props.view.segments.filter(segment => segment.kind === 'chain').length)
const displayText = computed(() => props.view.assistantText.trim())
const hasOutput = computed(() => hasAssistantOutput(props.view))
const errorText = computed(() => props.view.liveError || props.view.error?.message || null)
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
const errorTitle = computed(() => {
  const code = props.view.error?.code ?? props.view.liveErrorCode
  return (code && ERROR_TITLES[code]) || '生成失败'
})
// 认证、额度、上下文超限这类错误原样重试不会成功，先不给重试入口
const errorRetryable = computed(() => props.view.error?.retryable !== false)


const note = computed(() => {
  if (props.view.interrupted) {
    if (props.hasBatch) return null
    return '这一轮需要人工确认或外部结果，当前版本暂不提供继续操作；已产生的内容保留在过程中。'
  }
  if (props.view.cancelled) return '生成已停止。'
  if (props.view.status === 'failed' && !errorText.value) return '生成中断，可以重试。'
  if (!hasOutput.value && !isStreaming.value) {
    if (props.hasBatch) return null
    return '本轮没有返回可展示的内容。'
  }
  return null
})

const canRetryFromNote = computed(() => props.view.status === 'failed' && !errorText.value)

async function retry(): Promise<void> {
  try {
    await chat.regenerate(props.run)
  } catch (error) {
    toast.error('重试失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <div class="min-w-0">
    <template v-for="(segment, index) in view.segments" :key="segment.id">
      <ThinkingChain
        v-if="segment.kind === 'chain'"
        :chain="segment.entries"
        :plan="index === lastChainIndex ? view.plan : null"
        :is-streaming="isStreaming && segment.streaming"
        :status="isStreaming && !segment.streaming ? 'completed' : view.status"
        :started-at="chainCount === 1 && index === lastChainIndex ? run.created_at : null"
        :ended-at="chainCount === 1 && !isStreaming ? run.updated_at : null"
        :default-open="ui.autoExpandThinking || (isLast && index === lastChainIndex)"
        :default-details-open="ui.autoExpandToolDetails"
      />

      <ArtifactBlock
        v-else-if="segment.kind === 'artifact'"
        :media="segment.media"
        :credits="segment.credits"
      />

      <MarkdownMessage
        v-else
        :content="segment.text"
        :streaming="isStreaming && segment.streaming"
      />
    </template>

    <ArtifactSkeleton v-if="view.generatingImage" />

    <TurnFiles :media="view.attachments" />

    <FlightLoader v-if="isStreaming" class="mt-4" />

    <div
      v-if="errorText"
      class="mt-4 rounded-xl border border-destructive/20 bg-destructive/[0.04] px-4 py-3"
    >
      <div class="flex items-center gap-2">
        <AlertTriangle class="size-3.5 shrink-0 text-destructive" />
        <span class="text-[12.5px] font-medium text-destructive">{{ errorTitle }}</span>
        <button
          v-if="isLast && !chat.busy && errorRetryable"
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
        v-if="canRetryFromNote && isLast && !chat.busy"
        type="button"
        class="shrink-0 rounded-full border border-destructive/25 px-2.5 py-0.5 text-[11.5px] text-destructive transition-colors hover:bg-destructive/10"
        @click="retry"
      >
        重试
      </button>
    </div>

    <SourcesRow v-if="view.sources.length && !isStreaming" :sources="view.sources" />

    <slot name="pending" />

    <AssistantActions
      v-if="!isStreaming && !hideActions"
      :run="run"
      :content="displayText"
      :usage="run.usage"
      :is-last="isLast"
      :is-streaming="isStreaming"
    />
  </div>
</template>
