<script setup lang="ts">
import { computed } from 'vue'

import { buildPendingBatches, type PendingBatch } from '@/lib/pending'
import { mergeTurnViews, buildTurnView, hasUserOutput } from '@/lib/turnModel'
import { mergeTurnRuns, type TurnGroup } from '@/lib/turns'
import TurnShell from '@/components/turn/TurnShell.vue'
import { useChatStore } from '@/stores/chat'
import UserTurn from './UserTurn.vue'

const props = defineProps<{
  group: TurnGroup
  isLast: boolean
}>()

const chat = useChatStore()

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
  const merged = mergeTurnViews(baseView, liveView)
  // 同一 run 续写：先把这条 run 已落库的前半段铺回来，再接实时段。
  // 用户字段只保留一份，否则 run 自己的 user text 会被算两次。
  const historyView = chat.resumedLiveRunId === currentLive.runId && liveEntry.value
    ? buildTurnView(liveEntry.value, null, chat.toolResultsByCallId)
    : null
  if (!historyView) return merged
  const combined = mergeTurnViews(historyView, merged)
  combined.userText = merged.userText
  combined.userImages = merged.userImages
  combined.userVideos = merged.userVideos
  combined.userResources = merged.userResources
  return combined
})

const hasUser = computed(() => hasUserOutput(view.value))
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
  return pendingBatches.value
})
const displayView = computed(() => {
  const current = view.value
  if (current.interrupted && batches.value.length && batches.value.every(isSettled)) {
    return { ...current, status: 'completed' as const, interrupted: false }
  }
  return current
})

</script>

<template>
  <article class="group/turn flex flex-col gap-4">
    <TurnShell
      :run="mergedRun"
      :view="displayView"
      :is-last="isLast"
      :has-batch="hasBatch"
      :has-pending-batch="hasPendingBatch"
      :hide-actions="hasPendingBatch"
      :interactions="visibleBatches"
    >
      <template #user>
        <UserTurn v-if="hasUser" :run="group.run" :view="view" />
      </template>
    </TurnShell>
  </article>
</template>
