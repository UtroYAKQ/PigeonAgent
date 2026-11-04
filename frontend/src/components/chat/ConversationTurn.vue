<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { AlertTriangle } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { errorMessage } from '@/lib/http'
import {
  buildPendingBatches,
  isPreviewOnlyBatch,
  isPreviewTool,
  previewPayload,
  type PendingBatch,
} from '@/lib/pending'
import { mergeTurnViews, buildTurnView, hasUserOutput } from '@/lib/turnModel'
import { mergeTurnRuns, type TurnGroup } from '@/lib/turns'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'
import AssistantTurn from './AssistantTurn.vue'
import ContextCheckpoint from './ContextCheckpoint.vue'
import PendingBatchCard from './PendingBatchCard.vue'
import UserTurn from './UserTurn.vue'

const props = defineProps<{
  group: TurnGroup
  isLast: boolean
}>()

const chat = useChatStore()
const panels = usePanelStore()
const isWide = useMediaQuery('(min-width: 1280px)')
const attemptedPreviews = new Set<string>()
// preview-only 批次不渲染确认卡：自动 resume 一旦失败，页面上就没有任何出口，
// 所以失败要单独留痕并给一个重试按钮，别让人只能刷新页面
const previewFailures = reactive<Record<string, string>>({})

const previewFailure = computed(() => Object.values(previewFailures)[0] ?? null)

function retryPreviews(): void {
  for (const key of Object.keys(previewFailures)) delete previewFailures[key]
  maybeHandlePreviews()
}

const mergedRun = computed(() => mergeTurnRuns(props.group.runs) ?? props.group.run)
const liveEntry = computed(() => {
  const id = chat.liveRun?.runId
  return id ? props.group.runs.find(run => run.id === id) ?? null : null
})
const live = computed(() => (liveEntry.value ? chat.liveRun : null))

const view = computed(() => {
  const currentLive = live.value
  if (!currentLive) {
    return buildTurnView(mergedRun.value, null, chat.toolResultsByCallId)
  }
  const baseRuns = props.group.runs.filter(run => run.id !== currentLive.runId)
  const baseRun = mergeTurnRuns(baseRuns)
  const baseView = baseRun
    ? buildTurnView(baseRun, null, chat.toolResultsByCallId)
    : null
  const liveView = buildTurnView(
    liveEntry.value ?? mergedRun.value,
    currentLive,
    chat.toolResultsByCallId,
  )
  return mergeTurnViews(baseView, liveView)
})

const hasUser = computed(() => hasUserOutput(view.value))
const liveCompaction = computed(() => {
  if (!live.value || view.value.compactions.length) return null
  return live.value.compaction
})
const batches = computed(() => buildPendingBatches(mergedRun.value, chat.toolResultsByCallId))
const hasBatch = computed(() => batches.value.length > 0)
/** 工具结果落回快照，或者答案已经提交成功，都算这批处理完了。 */
function isSettled(batch: PendingBatch): boolean {
  return (
    batch.resolved
    || chat.isInterruptResumed(batch.interruptId)
    || chat.resumingInterruptId === batch.interruptId
  )
}
const pendingBatches = computed(() => batches.value.filter(batch => !isSettled(batch)))
const hasPendingBatch = computed(() => pendingBatches.value.length > 0)
const visibleBatches = computed(() => {
  // 续跑那一轮还在流式时，旧批次的工具结果尚未落库；这时卡片一定是不可提交的，
  // 先藏起来，等 run 结束再看它是否真的还没解决，避免整段流式期间挂着一张灰卡。
  if (chat.busy) return []
  return pendingBatches.value.filter(batch => !isPreviewOnlyBatch(batch))
})
const displayView = computed(() => {
  const current = view.value
  if (current.interrupted && batches.value.length && batches.value.every(isSettled)) {
    return { ...current, status: 'completed' as const, interrupted: false }
  }
  return current
})

function openPreviewsFor(batch: PendingBatch): void {
  if (!chat.currentSessionId) return
  for (const tool of batch.pendingCalls.filter(item => isPreviewTool(item.toolName))) {
    const payload = previewPayload(tool)
    if (!payload) continue
    panels.openPreview({
      sessionId: chat.currentSessionId,
      toolCallId: tool.toolCallId,
      title: payload.title,
      html: payload.html,
    })
  }
}

function maybeHandlePreviews(): void {
  if (chat.busy) return
  for (const batch of pendingBatches.value) {
    const previews = batch.pendingCalls.filter(tool => isPreviewTool(tool.toolName))
    if (!previews.length) continue
    const previewOnly = isPreviewOnlyBatch(batch)

    // 尝试过预览的批次不再重复触发：resume 失败时防止每次 busy 翻转都重发一遍
    if (attemptedPreviews.has(batch.interruptId)) continue
    attemptedPreviews.add(batch.interruptId)
    if (previewOnly || isWide.value) openPreviewsFor(batch)

    if (!previewOnly) continue
    const calls = Object.fromEntries(
      batch.pendingCalls.map(tool => [tool.toolCallId, { opened: true }]),
    )
    void chat
      .resumePendingBatch({ interruptId: batch.interruptId, approvals: {}, calls })
      .then(() => {
        delete previewFailures[batch.interruptId]
      })
      .catch((error: unknown) => {
        // 失败不算"尝试过"：留着标记会让这个批次在本次会话里再也无法自动处理
        attemptedPreviews.delete(batch.interruptId)
        previewFailures[batch.interruptId] = errorMessage(error)
        toast.error('自动打开预览失败', { description: errorMessage(error) })
      })
  }
}

watch(
  [pendingBatches, () => chat.busy],
  () => {
    if (!chat.busy) maybeHandlePreviews()
  },
  { immediate: true },
)
</script>

<template>
  <article class="group/turn flex flex-col gap-4">
    <ContextCheckpoint
      v-if="liveCompaction"
      :state="liveCompaction.status"
      :summary="liveCompaction.summary"
      :tokens-before="liveCompaction.tokensBefore"
    />
    <ContextCheckpoint
      v-for="item in view.compactions"
      :key="item.id"
      state="done"
      :summary="item.summary"
      :tokens-before="item.tokens_before || null"
    />
    <UserTurn v-if="hasUser" :run="group.run" :view="view" />
    <AssistantTurn
      :run="mergedRun"
      :view="displayView"
      :is-last="isLast"
      :has-batch="hasBatch"
      :hide-actions="hasPendingBatch"
    >
      <template #pending>
        <PendingBatchCard
          v-for="batch in visibleBatches"
          :key="batch.interruptId"
          :batch="batch"
        />
      </template>
    </AssistantTurn>

    <div
      v-if="previewFailure"
      class="flex flex-wrap items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/[0.04] px-3.5 py-2.5"
    >
      <AlertTriangle class="size-3.5 shrink-0 text-destructive" />
      <span class="min-w-0 flex-1 text-[12px] leading-5 text-muted-foreground">
        预览没有打开，生成已暂停：{{ previewFailure }}
      </span>
      <button
        type="button"
        class="shrink-0 rounded-full border border-destructive/25 px-2.5 py-0.5 text-[11.5px] text-destructive transition-colors hover:bg-destructive/10"
        @click="retryPreviews"
      >
        重试
      </button>
    </div>
  </article>
</template>
