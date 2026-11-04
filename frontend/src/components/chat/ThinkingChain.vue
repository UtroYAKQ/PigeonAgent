<script setup lang="ts">
import { computed, defineAsyncComponent, h, nextTick, ref, watch } from 'vue'
import { Check, ChevronDown, Circle, CircleAlert, CircleSlash, ListChecks, Loader2 } from '@lucide/vue'

import { formatDuration } from '@/lib/format'
import type { PlanState, ToolStep } from '@/lib/tools'
import type { ChainEntry } from '@/lib/turnModel'
import type { RunStatus } from '@/types/api'
import SonarDot from './SonarDot.vue'

const ToolOutput = defineAsyncComponent({
  loader: () => import('./ToolOutput.vue'),
  delay: 100,
  loadingComponent: {
    render: () => h('div', { class: 'rounded-lg border border-border bg-surface px-3 py-2 text-[11.5px] text-muted-foreground' }, '正在加载输出…'),
  },
})

const props = withDefaults(
  defineProps<{
    chain: ChainEntry[]
    plan: PlanState | null
    isStreaming: boolean
    status: RunStatus | 'streaming'
    startedAt?: string | null
    endedAt?: string | null
    defaultOpen?: boolean
    defaultDetailsOpen?: boolean
  }>(),
  {
    startedAt: null,
    endedAt: null,
    defaultOpen: false,
    defaultDetailsOpen: false,
  },
)

const open = ref(props.defaultOpen || props.isStreaming)
const collapsedReasoning = ref<Set<string>>(new Set())
const autoExpanded = new Set<string>(
  props.defaultDetailsOpen
    ? props.chain.flatMap(entry => (
        entry.kind === 'tool' && (entry.step.result != null || entry.step.args != null)
          ? [entry.step.id]
          : []
      ))
    : [],
)
const expanded = ref<Set<string>>(new Set(autoExpanded))
const reasoningBoxes = new Map<string, HTMLElement>()
/** 距底部这么近就算「读完了」，恢复跟随 */
const RESUME_FOLLOW_GAP = 8
// 用户在推理盒里往上翻就是「正在读」，此时别再抢滚动条。缺省跟随。
const reasoningFollowed = new Map<string, boolean>()
const reasoningTops = new Map<string, number>()

watch(
  () => props.isStreaming,
  (streaming) => {
    if (streaming) open.value = true
  },
)

const steps = computed(() => props.chain.flatMap(entry => (entry.kind === 'tool' ? [entry.step] : [])))
const failedSteps = computed(() => steps.value.filter(step => step.state === 'failed'))
const succeededSteps = computed(() => steps.value.filter(step => step.state === 'success'))

const displayChain = computed(() => {
  if (!props.plan) return props.chain
  return props.chain.filter(entry =>
    entry.kind !== 'tool' || (entry.step.name !== 'plan_set' && entry.step.name !== 'plan_show'),
  )
})

const hasContent = computed(() => Boolean(props.chain.length || props.plan))

const activeStep = computed(() => steps.value.find(step => step.state === 'running' || step.state === 'waiting'))

const activeReasoning = computed(() => {
  for (let index = props.chain.length - 1; index >= 0; index -= 1) {
    const entry = props.chain[index]
    if (entry?.kind === 'reasoning' && entry.text) return entry
  }
  return null
})

const headerLabel = computed(() => {
  if (props.isStreaming) {
    if (activeStep.value) return activeStep.value.label
    if (props.plan) return '正在执行计划'
    if (activeReasoning.value?.streaming) return '正在思考'
    return '正在生成回复'
  }
  if (props.status === 'failed') {
    return steps.value.length ? `执行中断 · ${steps.value.length} 个步骤` : '生成失败'
  }
  if (props.status === 'interrupted') {
    return steps.value.length ? `已暂停 · ${steps.value.length} 个步骤` : '等待后续操作'
  }
  const duration = props.startedAt ? formatDuration(props.startedAt, props.endedAt) : null
  if (props.plan && !steps.value.length) {
    return `执行计划 ${props.plan.progress}${duration ? ` · 用时 ${duration}` : ''}`
  }
  if (steps.value.length) {
    const plan = props.plan ? ` · 计划 ${props.plan.progress}` : ''
    return `已完成 ${steps.value.length} 个步骤${plan}${duration ? ` · 用时 ${duration}` : ''}`
  }
  return `思考过程${duration ? ` · 用时 ${duration}` : ''}`
})

function hasBody(step: ToolStep): boolean {
  return step.result != null || step.args != null
}

function isReasoningCollapsed(id: string): boolean {
  return collapsedReasoning.value.has(id)
}

function toggleReasoning(id: string): void {
  const next = new Set(collapsedReasoning.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedReasoning.value = next
}

function setReasoningBox(id: string, element: unknown): void {
  if (element instanceof HTMLElement) reasoningBoxes.set(id, element)
  else {
    reasoningBoxes.delete(id)
    reasoningFollowed.delete(id)
    reasoningTops.delete(id)
  }
}

/** 内容长高不会触发 scroll，只有真实滚动才会——所以这里的判断只反映用户意图。 */
function onReasoningScroll(id: string, event: Event): void {
  const element = event.target
  if (!(element instanceof HTMLElement)) return
  const top = element.scrollTop
  const distance = element.scrollHeight - top - element.clientHeight
  if (top < (reasoningTops.get(id) ?? top)) reasoningFollowed.set(id, false)
  else if (distance < RESUME_FOLLOW_GAP) reasoningFollowed.set(id, true)
  reasoningTops.set(id, top)
}

function toggleStep(id: string): void {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

watch(
  steps,
  (list) => {
    if (!props.defaultDetailsOpen) return
    const next = new Set(expanded.value)
    let changed = false
    for (const step of list) {
      if (hasBody(step) && !autoExpanded.has(step.id)) {
        autoExpanded.add(step.id)
        next.add(step.id)
        changed = true
      }
    }
    if (changed) expanded.value = next
  },
  { deep: true },
)

watch(
  () => {
    if (!props.isStreaming) return null
    const entry = activeReasoning.value
    return entry ? `${entry.id}:${entry.text.length}` : null
  },
  async (key) => {
    if (!key) return
    await nextTick()
    const entry = activeReasoning.value
    if (!entry || reasoningFollowed.get(entry.id) === false) return
    const element = reasoningBoxes.get(entry.id)
    if (element) element.scrollTop = element.scrollHeight
  },
)
</script>

<template>
  <div v-if="hasContent" class="not-prose my-3.5">
    <button
      type="button"
      class="group/chain flex w-full items-center gap-2 rounded-md py-0.5 text-left text-[14px] leading-5 text-muted-foreground transition-colors hover:text-foreground"
      :aria-expanded="open"
      @click="open = !open"
    >
      <SonarDot v-if="isStreaming" :size="6" class="shrink-0" />
      <span
        v-else
        class="grid size-3.5 shrink-0 place-items-center text-muted-foreground/70"
      >
        <CircleAlert v-if="status === 'failed'" class="size-3.5 text-muted-foreground" />
        <Check v-else-if="status !== 'interrupted'" class="size-3.5" :stroke-width="2" />
        <CircleSlash v-else class="size-3.5" />
      </span>
      <span class="truncate">{{ headerLabel }}</span>
      <span
        v-if="steps.length && !isStreaming"
        class="shrink-0 text-[12px] text-muted-foreground"
      >
        成功 {{ succeededSteps.length }} · 失败 {{ failedSteps.length }}
      </span>
      <ChevronDown
        class="size-3.5 shrink-0 text-muted-foreground/60 transition-transform duration-150"
        :class="open ? 'rotate-180' : ''"
      />
    </button>

    <div v-show="open" class="mt-3 pl-[3px]">
      <div v-if="plan" class="mb-4 rounded-xl border border-border/80 bg-surface/60 px-4 py-3.5">
        <div class="flex items-center gap-2 text-[12px] text-muted-foreground">
          <ListChecks class="size-3.5" />
          <span>执行计划</span>
          <span class="ml-auto font-mono text-[10.5px]">{{ plan.progress }}</span>
        </div>
        <ul class="mt-2.5 space-y-2">
          <li
            v-for="item in plan.items"
            :key="item.index"
            class="flex items-start gap-2 text-[13.5px] leading-5"
            :class="item.status === 'active' ? 'text-foreground' : item.status === 'done' ? 'text-muted-foreground' : 'text-muted-foreground/65'"
          >
            <span class="mt-[3px] grid size-3.5 shrink-0 place-items-center">
              <Check v-if="item.status === 'done'" class="size-3.5" :stroke-width="2" />
              <SonarDot v-else-if="item.status === 'active'" :size="6" />
              <Circle v-else class="size-3" :stroke-width="1.6" />
            </span>
            <span class="min-w-0">{{ item.content }}</span>
          </li>
        </ul>
      </div>

      <ol class="relative">
        <li
          v-for="(entry, index) in displayChain"
          :key="entry.kind === 'reasoning' ? `reasoning-${entry.id}` : `tool-${entry.step.id}`"
          class="relative flex gap-2.5"
          :class="index === displayChain.length - 1 && !isStreaming ? 'pb-0' : 'pb-3.5'"
        >
          <div class="relative flex w-3.5 shrink-0 flex-col items-center pt-[7px]">
            <template v-if="entry.kind === 'reasoning'">
              <SonarDot v-if="isStreaming && entry.streaming" :size="6" />
              <span v-else class="size-1.5 rounded-full bg-muted-foreground/35" />
            </template>
            <template v-else>
              <SonarDot v-if="entry.step.state === 'running' || entry.step.state === 'waiting'" :size="6" />
              <span
                v-else
                class="size-1.5 rounded-full"
                :class="entry.step.state === 'failed'
                  ? 'bg-destructive'
                  : entry.step.state === 'interrupted'
                    ? 'bg-muted-foreground/45'
                    : 'bg-muted-foreground/35'"
              />
            </template>
            <span class="absolute left-1/2 top-[15px] bottom-[-4px] w-px -translate-x-1/2 bg-border" />
          </div>

          <div class="min-w-0 flex-1">
            <template v-if="entry.kind === 'reasoning'">
              <button
                type="button"
                class="flex items-center gap-1.5 text-[13px] leading-5 text-muted-foreground transition-colors hover:text-foreground"
                :aria-expanded="!isReasoningCollapsed(entry.id)"
                @click="toggleReasoning(entry.id)"
              >
                <span>推理过程</span>
                <ChevronDown
                  class="size-3.5 text-muted-foreground/60 transition-transform duration-150"
                  :class="isReasoningCollapsed(entry.id) ? '' : 'rotate-180'"
                />
              </button>
              <div
                v-show="!isReasoningCollapsed(entry.id)"
                :ref="element => setReasoningBox(entry.id, element)"
                class="mt-1.5 max-h-[320px] overflow-y-auto whitespace-pre-wrap break-words pr-1 text-[13.5px] leading-[1.72] text-muted-foreground/90"
                @scroll="onReasoningScroll(entry.id, $event)"
              >
                {{ entry.text }}
              </div>
            </template>

            <template v-else>
              <button
                type="button"
                class="group/step flex w-full items-center gap-2 text-left"
                :class="hasBody(entry.step) ? 'cursor-pointer' : 'cursor-default'"
                :disabled="!hasBody(entry.step)"
                @click="hasBody(entry.step) && toggleStep(entry.step.id)"
              >
                <span class="flex min-w-0 flex-1 items-center gap-2">
                  <CircleAlert
                    v-if="entry.step.state === 'failed'"
                    class="size-3.5 shrink-0 text-destructive"
                  />
                  <span class="flex min-w-0 items-baseline gap-2">
                    <span
                      class="shrink-0 text-[14px] leading-5"
                      :class="entry.step.state === 'failed' ? 'text-destructive' : entry.step.state === 'running' || entry.step.state === 'waiting' ? 'text-foreground' : 'text-muted-foreground'"
                    >
                      {{ entry.step.label }}
                    </span>
                    <span v-if="entry.step.detail" class="truncate text-[12px] leading-4 text-muted-foreground/70">
                      {{ entry.step.detail }}
                    </span>
                  </span>
                  <ChevronDown
                    v-if="hasBody(entry.step)"
                    class="size-3.5 shrink-0 text-muted-foreground/45 transition-transform duration-150 group-hover/step:text-muted-foreground"
                    :class="expanded.has(entry.step.id) ? 'rotate-180' : ''"
                  />
                </span>
                <Loader2 v-if="!hasBody(entry.step) && entry.step.state === 'running'" class="mt-1 size-3 shrink-0 animate-spin text-muted-foreground" />
              </button>

              <div v-if="hasBody(entry.step) && expanded.has(entry.step.id)" class="mt-2.5">
                <ToolOutput :step="entry.step" />
              </div>
            </template>
          </div>
        </li>
      </ol>
    </div>
  </div>
</template>
