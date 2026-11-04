<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Info,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  Volume2,
  VolumeX,
} from '@lucide/vue'

import MessageAction from '@/components/ai-elements/message/MessageAction.vue'
import MessageActions from '@/components/ai-elements/message/MessageActions.vue'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { errorMessage } from '@/lib/http'
import { formatTokens, formatDuration } from '@/lib/format'
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import { plainTextFromMarkdown } from '@/lib/markdown'
import { useChatStore } from '@/stores/chat'
import type { SessionRun, TokenUsage } from '@/types/api'

const props = defineProps<{
  run: SessionRun
  content: string
  usage: TokenUsage
  isLast: boolean
  isStreaming: boolean
}>()

const chat = useChatStore()
const { copied, copyText } = useCopyFeedback()
const speaking = ref(false)
const canSpeak = ref(false)
const feedback = ref<'up' | 'down' | null>(null)

const hasText = computed(() => Boolean(props.content.trim()))
const branch = computed(() => props.run.branch)

onMounted(() => {
  canSpeak.value = typeof window !== 'undefined' && 'speechSynthesis' in window
  feedback.value = (localStorage.getItem(`pigeon.feedback.${props.run.id}`) as 'up' | 'down' | null) ?? null
})

onBeforeUnmount(() => {
  if (canSpeak.value) window.speechSynthesis.cancel()
})

async function copy(): Promise<void> {
  await copyText(props.content, () => toast.error('复制失败'))
}

async function regenerate(): Promise<void> {
  try {
    await chat.regenerate(props.run)
  } catch (error) {
    toast.error('重新生成失败', { description: errorMessage(error) })
  }
}

function speak(): void {
  if (!canSpeak.value) return
  if (speaking.value) {
    window.speechSynthesis.cancel()
    speaking.value = false
    return
  }
  const text = plainTextFromMarkdown(props.content).slice(0, 4000)
  if (!text) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = navigator.language || 'zh-CN'
  utterance.rate = 1
  utterance.onend = () => {
    speaking.value = false
  }
  utterance.onerror = () => {
    speaking.value = false
  }
  speaking.value = true
  window.speechSynthesis.speak(utterance)
}

function rate(value: 'up' | 'down'): void {
  feedback.value = feedback.value === value ? null : value
  if (feedback.value) localStorage.setItem(`pigeon.feedback.${props.run.id}`, feedback.value)
  else localStorage.removeItem(`pigeon.feedback.${props.run.id}`)
}

async function switchBranch(direction: -1 | 1): Promise<void> {
  if (!branch.value || chat.busy) return
  const total = branch.value.total
  const next = (branch.value.position - 1 + direction + total) % total
  try {
    await chat.switchBranch(props.run, next)
  } catch (error) {
    toast.error('切换版本失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <div
    v-if="!isStreaming"
    class="mt-3 flex min-h-7 items-center gap-1.5 opacity-100 transition-opacity duration-150"
    :class="isLast ? 'sm:opacity-100' : 'sm:opacity-0 sm:group-hover/turn:opacity-100 sm:focus-within:opacity-100'"
  >
    <div v-if="branch && branch.total > 1" class="mr-1 flex items-center rounded-full border border-border">
      <button
        type="button"
        class="grid size-6 place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
        aria-label="上一个版本"
        :disabled="chat.busy"
        @click="switchBranch(-1)"
      >
        <ChevronLeft class="size-4" />
      </button>
      <span class="px-1 font-mono text-[10.5px] tabular-nums text-muted-foreground">
        {{ branch.position }}/{{ branch.total }}
      </span>
      <button
        type="button"
        class="grid size-6 place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
        aria-label="下一个版本"
        :disabled="chat.busy"
        @click="switchBranch(1)"
      >
        <ChevronRight class="size-4" />
      </button>
    </div>

    <MessageActions class="gap-0.5">
      <MessageAction
        v-if="hasText"
        tooltip="复制"
        class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        @click="copy"
      >
        <Check v-if="copied" class="size-4" />
        <Copy v-else class="size-4" />
      </MessageAction>

      <MessageAction
        v-if="isLast && (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled')"
        tooltip="重新生成"
        class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        :disabled="chat.busy"
        @click="regenerate"
      >
        <RefreshCw class="size-4" />
      </MessageAction>

      <MessageAction
        v-if="canSpeak && hasText"
        :tooltip="speaking ? '停止朗读' : '朗读'"
        class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        @click="speak"
      >
        <VolumeX v-if="speaking" class="size-4" />
        <Volume2 v-else class="size-4" />
      </MessageAction>

      <MessageAction
        tooltip="有帮助"
        class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        :class="feedback === 'up' ? '!text-brand' : ''"
        @click="rate('up')"
      >
        <ThumbsUp class="size-4" :fill="feedback === 'up' ? 'currentColor' : 'none'" />
      </MessageAction>

      <MessageAction
        tooltip="没帮上忙"
        class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        :class="feedback === 'down' ? '!text-brand' : ''"
        @click="rate('down')"
      >
        <ThumbsDown class="size-4" :fill="feedback === 'down' ? 'currentColor' : 'none'" />
      </MessageAction>

      <Popover>
        <PopoverTrigger as-child>
          <Button
            variant="ghost"
            size="icon-sm"
            class="size-8 rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
            aria-label="本轮用量"
          >
            <Info class="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" class="w-[240px] rounded-xl p-3.5">
          <div class="flex items-baseline justify-between">
            <p class="text-[12.5px] font-medium">本轮用量</p>
            <p class="font-mono text-[11px] text-muted-foreground">{{ formatTokens(usage.total_tokens) }} tokens</p>
          </div>
          <div class="mt-2.5 space-y-1.5 text-[12px]">
            <div class="flex justify-between"><span class="text-muted-foreground">输入</span><span class="font-mono">{{ formatTokens(usage.input_tokens) }}</span></div>
            <div v-if="usage.cache_read_tokens" class="flex justify-between"><span class="text-muted-foreground">其中缓存</span><span class="font-mono">{{ formatTokens(usage.cache_read_tokens) }}</span></div>
            <div class="flex justify-between"><span class="text-muted-foreground">输出</span><span class="font-mono">{{ formatTokens(usage.output_tokens) }}</span></div>
            <div class="flex justify-between"><span class="text-muted-foreground">请求</span><span class="font-mono">{{ usage.requests }}</span></div>
            <div class="flex justify-between border-t border-border pt-1.5"><span class="text-muted-foreground">用时</span><span class="font-mono">{{ formatDuration(run.created_at, run.updated_at) }}</span></div>
          </div>
        </PopoverContent>
      </Popover>
    </MessageActions>
  </div>
</template>
