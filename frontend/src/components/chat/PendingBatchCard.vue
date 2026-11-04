<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Check, ChevronLeft, ChevronRight, Globe2, Loader2, MessageCircleQuestion, ShieldCheck, X } from '@lucide/vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/http'
import { parseJsonLike, stringifyValue } from '@/lib/format'
import {
  askQuestions,
  isPreviewTool,
  type PendingBatch,
  type PendingTool,
} from '@/lib/pending'
import { askAnswersPayload, type AskQuestion } from '@/lib/frontendTools'
import { useChatStore } from '@/stores/chat'

const props = defineProps<{ batch: PendingBatch }>()
const chat = useChatStore()

const decisions = reactive<Record<string, 'approved' | 'denied'>>({})
const externalText = reactive<Record<string, string>>({})
// toolCallId → 题号 → 已选选项文字
const chosen = reactive<Record<string, Record<number, string[]>>>({})
const submitting = ref(false)
const error = ref<string | null>(null)

const pendingApprovals = computed(() => props.batch.pendingApprovals)
// 提问调用要渲染成问卷；形状不对的退回通用结果输入，不给半张卡
const askItems = computed(() =>
  props.batch.pendingCalls
    .map(tool => ({ tool, questions: askQuestions(tool) }))
    .filter((item): item is { tool: PendingTool; questions: AskQuestion[] } =>
      Boolean(item.questions),
    ),
)
const previewTools = computed(() =>
  props.batch.pendingCalls.filter(tool => isPreviewTool(tool.toolName)),
)
const externalTools = computed(() =>
  props.batch.pendingCalls.filter(
    tool => !isPreviewTool(tool.toolName) && !askQuestions(tool),
  ),
)

const title = computed(() => {
  if (askItems.value.length && !pendingApprovals.value.length && !externalTools.value.length) {
    return '需要你回答'
  }
  if (pendingApprovals.value.length && externalTools.value.length) return '需要你的确认和结果'
  if (pendingApprovals.value.length) return '需要你的确认'
  return '需要你的结果'
})

const subtitle = computed(() => {
  const parts: string[] = []
  if (askItems.value.length) parts.push(`${askQuestionCount.value} 个问题待回答`)
  if (pendingApprovals.value.length) parts.push(`${pendingApprovals.value.length} 个操作待审批`)
  if (externalTools.value.length) parts.push(`${externalTools.value.length} 个外部结果待填写`)
  return parts.join(' · ') || '完成后继续生成'
})

const askQuestionCount = computed(() =>
  askItems.value.reduce((total, item) => total + item.questions.length, 0),
)

/** 一次问多题时逐题翻页；只有一题就保持原来的整列样子，不加任何控件。 */
const askPages = computed(() =>
  askItems.value.flatMap(item =>
    item.questions.map((question, index) => ({
      toolCallId: item.tool.toolCallId,
      question,
      index,
    })),
  ),
)
const page = ref(0)
// 批次变化时页数可能变少，这里兜一下，别让指针越界渲染成空白题
const currentPage = computed(
  () => askPages.value[Math.min(page.value, askPages.value.length - 1)] ?? null,
)
watch(
  () => askPages.value.length,
  (length) => {
    if (page.value > length - 1) page.value = Math.max(0, length - 1)
  },
)

function stepPage(delta: number): void {
  const last = askPages.value.length - 1
  page.value = Math.min(Math.max(page.value + delta, 0), last)
}

function selectionsOf(toolCallId: string): Record<number, string[]> {
  const existing = chosen[toolCallId]
  if (!existing) {
    chosen[toolCallId] = {}
    return chosen[toolCallId]
  }
  return existing
}

function isChosen(toolCallId: string, index: number, label: string): boolean {
  return (chosen[toolCallId]?.[index] ?? []).includes(label)
}

function toggleOption(
  toolCallId: string,
  question: AskQuestion,
  index: number,
  label: string,
): void {
  const picked = selectionsOf(toolCallId)
  const current = picked[index] ?? []
  if (question.multiSelect) {
    picked[index] = current.includes(label)
      ? current.filter(item => item !== label)
      : [...current, label]
    return
  }
  // 单选：再点同一个等于取消，点别的直接换掉
  picked[index] = current.length === 1 && current[0] === label ? [] : [label]
}

function argEntries(tool: PendingTool): [string, unknown][] {
  const value = parseJsonLike(tool.args)
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>)
}

function valueText(value: unknown): string {
  if (typeof value === 'string') return value
  return stringifyValue(value)
}

function isBlockValue(value: unknown): boolean {
  return typeof value === 'string' && (value.includes('\n') || value.length > 100)
}

function metadataText(metadata: unknown): string {
  const value = parseJsonLike(metadata)
  if (!value || typeof value !== 'object') return typeof value === 'string' ? value : ''
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}: ${valueText(item)}`)
    .join(' · ')
}

function setDecision(tool: PendingTool, decision: 'approved' | 'denied'): void {
  decisions[tool.toolCallId] = decision
}

function unansweredCount(): number {
  let missing = 0
  for (const item of askItems.value) {
    for (let index = 0; index < item.questions.length; index += 1) {
      if (!(chosen[item.tool.toolCallId]?.[index] ?? []).length) missing += 1
    }
  }
  return missing
}

const allApprovalsDecided = computed(() =>
  pendingApprovals.value.every(tool => Boolean(decisions[tool.toolCallId])),
)
const allExternalFilled = computed(() =>
  externalTools.value.every(tool => Boolean(externalText[tool.toolCallId]?.trim())),
)
const allAskAnswered = computed(() => unansweredCount() === 0)
const canSubmit = computed(() =>
  !submitting.value
  && !chat.busy
  && allApprovalsDecided.value
  && allExternalFilled.value
  && allAskAnswered.value,
)

const missingText = computed(() => {
  if (submitting.value) return '正在继续生成…'
  const missing: string[] = []
  const unanswered = unansweredCount()
  if (unanswered) missing.push(`${unanswered} 个问题待回答`)
  const approvalCount = pendingApprovals.value.filter(tool => !decisions[tool.toolCallId]).length
  if (approvalCount) missing.push(`${approvalCount} 项待确认`)
  const externalCount = externalTools.value.filter(tool => !externalText[tool.toolCallId]?.trim()).length
  if (externalCount) missing.push(`${externalCount} 个外部结果待填写`)
  return missing.length ? `还有 ${missing.join(' · ')}` : '完成后继续生成'
})

const submitLabel = computed(() => {
  if (submitting.value) return '正在继续'
  if (askItems.value.length && !pendingApprovals.value.length && !externalTools.value.length) {
    return '提交答案'
  }
  if (pendingApprovals.value.length && !externalTools.value.length && !askItems.value.length) {
    return '确认并继续'
  }
  return '提交并继续'
})

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  const approvals: Record<string, boolean> = {}
  for (const tool of pendingApprovals.value) {
    const decision = decisions[tool.toolCallId]
    if (!decision) return
    approvals[tool.toolCallId] = decision === 'approved'
  }
  const calls: Record<string, unknown> = {}
  for (const tool of externalTools.value) {
    const raw = externalText[tool.toolCallId]?.trim()
    if (!raw) return
    try {
      calls[tool.toolCallId] = JSON.parse(raw) as unknown
    } catch {
      calls[tool.toolCallId] = raw
    }
  }
  for (const item of askItems.value) {
    calls[item.tool.toolCallId] = askAnswersPayload(
      item.questions,
      chosen[item.tool.toolCallId] ?? {},
    )
  }
  // 预览调用不再显示单独按钮，继续时一并回填，避免批次卡在未决状态。
  for (const tool of previewTools.value) {
    calls[tool.toolCallId] = { opened: true }
  }

  submitting.value = true
  error.value = null
  try {
    await chat.resumePendingBatch({
      interruptId: props.batch.interruptId,
      approvals,
      calls,
    })
  } catch (err) {
    submitting.value = false
    error.value = errorMessage(err)
    toast.error('继续失败', { description: error.value })
  }
}
</script>

<template>
  <section class="mt-3 overflow-hidden rounded-lg border border-border bg-card text-card-foreground">
    <header class="flex items-start gap-2.5 px-4 py-3.5">
      <MessageCircleQuestion v-if="askItems.length" class="mt-0.5 size-4 shrink-0 text-muted-foreground" :stroke-width="1.8" />
      <ShieldCheck v-else-if="pendingApprovals.length" class="mt-0.5 size-4 shrink-0 text-muted-foreground" :stroke-width="1.8" />
      <Globe2 v-else class="mt-0.5 size-4 shrink-0 text-muted-foreground" :stroke-width="1.8" />
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h3 class="text-[13.5px] font-medium leading-5 text-foreground">{{ title }}</h3>
          <Badge variant="secondary" class="h-5 px-1.5 text-[10.5px] font-normal">
            {{ submitting ? '正在继续' : '待处理' }}
          </Badge>
        </div>
        <p class="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">{{ subtitle }}</p>
      </div>
    </header>

    <div class="space-y-4 px-4 pb-4">
      <div
        v-if="currentPage"
        :key="`${currentPage.toolCallId}-${currentPage.index}`"
        class="space-y-2"
      >
        <div class="flex items-start gap-2">
          <p class="min-w-0 flex-1 text-[13px] font-medium leading-5">{{ currentPage.question.question }}</p>
          <span v-if="askPages.length === 1" class="shrink-0 text-[11px] leading-5 text-muted-foreground">
            {{ currentPage.question.multiSelect ? '可多选' : '单选' }}
          </span>
          <div v-else class="flex shrink-0 items-center" role="group" aria-label="问题翻页">
            <button
              type="button"
              class="grid size-6 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
              aria-label="上一题"
              :disabled="page === 0 || submitting"
              @click="stepPage(-1)"
            >
              <ChevronLeft class="size-3.5" />
            </button>
            <span class="min-w-[32px] text-center text-[11.5px] leading-5 tabular-nums text-muted-foreground">
              {{ page + 1 }}/{{ askPages.length }}
            </span>
            <button
              type="button"
              class="grid size-6 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
              aria-label="下一题"
              :disabled="page >= askPages.length - 1 || submitting"
              @click="stepPage(1)"
            >
              <ChevronRight class="size-3.5" />
            </button>
          </div>
        </div>
        <div class="space-y-0.5">
          <button
            v-for="option in currentPage.question.options"
            :key="option.label"
            type="button"
            class="flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60 disabled:opacity-50"
            :class="isChosen(currentPage.toolCallId, currentPage.index, option.label) ? 'bg-muted/70' : ''"
            :aria-pressed="isChosen(currentPage.toolCallId, currentPage.index, option.label)"
            :disabled="submitting"
            @click="toggleOption(currentPage.toolCallId, currentPage.question, currentPage.index, option.label)"
          >
            <span
              class="mt-0.5 grid size-4 shrink-0 place-items-center border"
              :class="[
                currentPage.question.multiSelect ? 'rounded-[4px]' : 'rounded-full',
                isChosen(currentPage.toolCallId, currentPage.index, option.label)
                  ? 'border-brand bg-brand text-brand-foreground'
                  : 'border-input text-transparent',
              ]"
            >
              <Check class="size-2.5" :stroke-width="2.6" />
            </span>
            <span class="min-w-0">
              <span class="block text-[13px] leading-5">{{ option.label }}</span>
              <span
                v-if="option.description"
                class="mt-0.5 block text-[11.5px] leading-5 text-muted-foreground"
              >
                {{ option.description }}
              </span>
            </span>
          </button>
        </div>
      </div>

      <div
        v-if="pendingApprovals.length"
        class="space-y-3"
        :class="askItems.length ? 'border-t border-border/70 pt-4' : ''"
      >
        <div v-for="tool in pendingApprovals" :key="tool.toolCallId" class="space-y-2">
          <div class="flex items-center gap-2">
            <ShieldCheck class="size-3.5 shrink-0 text-muted-foreground" />
            <code class="min-w-0 truncate text-[12px] font-medium">{{ tool.toolName }}</code>
            <Badge variant="outline" class="ml-auto h-5 shrink-0 px-1.5 text-[10.5px] font-normal">
              需要确认
            </Badge>
          </div>
          <dl v-if="argEntries(tool).length" class="space-y-1 rounded-md bg-muted/40 px-3 py-2">
            <div
              v-for="[key, value] in argEntries(tool)"
              :key="key"
              class="grid grid-cols-[64px_minmax(0,1fr)] gap-2 text-[12px]"
            >
              <dt class="font-mono text-[11px] leading-5 text-muted-foreground">{{ key }}</dt>
              <dd class="min-w-0 text-foreground/85">
                <pre v-if="isBlockValue(value)" class="max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11.5px] leading-5">{{ valueText(value) }}</pre>
                <span v-else class="break-words font-mono">{{ valueText(value) }}</span>
              </dd>
            </div>
          </dl>
          <p v-else class="text-[11.5px] text-muted-foreground">无参数</p>
          <div class="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              class="h-8 flex-1 text-[12px]"
              :class="decisions[tool.toolCallId] === 'denied' ? 'bg-muted text-foreground' : ''"
              :disabled="submitting"
              @click="setDecision(tool, 'denied')"
            >
              <X class="size-3.5" />
              拒绝
            </Button>
            <Button
              :variant="decisions[tool.toolCallId] === 'approved' ? 'default' : 'outline'"
              size="sm"
              class="h-8 flex-1 text-[12px]"
              :disabled="submitting"
              @click="setDecision(tool, 'approved')"
            >
              <Check class="size-3.5" :stroke-width="2.2" />
              允许
            </Button>
          </div>
        </div>
      </div>

      <div
        v-if="externalTools.length"
        class="space-y-3"
        :class="askItems.length || pendingApprovals.length ? 'border-t border-border/70 pt-4' : ''"
      >
        <div v-for="tool in externalTools" :key="tool.toolCallId" class="space-y-2">
          <div class="flex items-center gap-2">
            <Globe2 class="size-3.5 shrink-0 text-muted-foreground" />
            <code class="min-w-0 truncate text-[12px] font-medium">{{ tool.toolName }}</code>
            <span v-if="tool.metadata" class="truncate text-[10.5px] text-muted-foreground">
              {{ metadataText(tool.metadata) }}
            </span>
            <Badge variant="outline" class="ml-auto h-5 shrink-0 px-1.5 text-[10.5px] font-normal">
              待填写
            </Badge>
          </div>
          <p v-if="argEntries(tool).length" class="line-clamp-2 break-words font-mono text-[11px] text-muted-foreground">
            {{ argEntries(tool).map(([key, value]) => `${key}: ${valueText(value)}`).join(' · ') }}
          </p>
          <Textarea
            v-model="externalText[tool.toolCallId]"
            :rows="2"
            placeholder="把调用返回的内容填进来，支持 JSON"
            :disabled="submitting"
            class="min-h-[64px] resize-none text-[12.5px] leading-5"
          />
        </div>
      </div>
    </div>

    <footer class="flex items-center gap-3 border-t border-border/70 px-4 py-2.5">
      <span v-if="error" class="min-w-0 flex-1 truncate text-[11.5px] text-destructive">{{ error }}</span>
      <span v-else class="min-w-0 flex-1 text-[11.5px] text-muted-foreground">{{ missingText }}</span>
      <Button
        size="sm"
        class="h-8 shrink-0 px-3 text-[12px]"
        :disabled="!canSubmit"
        @click="submit"
      >
        <Loader2 v-if="submitting" class="size-3.5 animate-spin" />
        {{ submitLabel }}
      </Button>
    </footer>
  </section>
</template>
