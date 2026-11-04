<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, Copy, Loader2 } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { sharesApi } from '@/api/shares'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { copyToClipboard } from '@/lib/clipboard'
import { errorMessage } from '@/lib/http'
import { formatDateTime } from '@/lib/format'
import type { SessionShare, UUID } from '@/types/api'

const OPTIONS = [
  { days: 7, label: '7 天' },
  { days: 30, label: '30 天' },
  { days: 90, label: '90 天' },
]

const props = defineProps<{
  open: boolean
  sessionId: UUID
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const days = ref(7)
const creating = ref(false)
const share = ref<SessionShare | null>(null)
const copied = ref(false)

const link = computed(() =>
  share.value ? `${window.location.origin}/s/${share.value.token}` : '',
)

// 链接是按会话签的：换到别的会话还留着上一条会误导
watch(
  () => props.sessionId,
  () => {
    share.value = null
    copied.value = false
  },
)

async function create(): Promise<void> {
  if (creating.value) return
  creating.value = true
  try {
    share.value = await sharesApi.create(props.sessionId, days.value)
    copied.value = false
  } catch (error) {
    toast.error('创建分享链接失败', { description: errorMessage(error) })
  } finally {
    creating.value = false
  }
}

async function copy(): Promise<void> {
  if (!link.value) return
  if (await copyToClipboard(link.value)) {
    copied.value = true
    return
  }
  toast.error('复制失败', { description: '浏览器拒绝了剪贴板访问，请手动选中链接复制' })
}
</script>

<template>
  <Dialog :open="props.open" @update:open="emit('update:open', $event)">
    <DialogContent class="max-w-[420px] rounded-2xl">
      <DialogHeader>
        <DialogTitle class="text-[17px] font-semibold tracking-[-0.02em]">
          分享这段对话
        </DialogTitle>
        <DialogDescription class="text-[13px] text-muted-foreground">
          访客无需登录即可只读查看正文与过程记录；到期后链接自动失效。
        </DialogDescription>
      </DialogHeader>

      <template v-if="!share">
        <div class="mt-1 grid gap-2">
          <span class="text-[12.5px] font-medium">有效期</span>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="option in OPTIONS"
              :key="option.days"
              type="button"
              class="h-9 rounded-lg border text-[13px] transition-colors"
              :class="days === option.days
                ? 'border-foreground/25 bg-muted/50 font-medium'
                : 'border-border bg-card text-muted-foreground hover:bg-muted/30'"
              :aria-pressed="days === option.days"
              @click="days = option.days"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <DialogFooter class="mt-4">
          <Button class="h-9" :disabled="creating" @click="create">
            <Loader2 v-if="creating" class="size-4 animate-spin" />
            <span>创建链接</span>
          </Button>
        </DialogFooter>
      </template>

      <template v-else>
        <label class="mt-1 grid gap-1.5 text-[12.5px] font-medium" for="share-link">
          链接
        </label>
        <input
          id="share-link"
          :value="link"
          readonly
          class="h-9 w-full rounded-lg border border-border bg-muted/30 px-2.5 font-mono text-[12px] outline-none"
          @focus="($event.target as HTMLInputElement).select()"
        >
        <p class="mt-2 text-[12px] leading-5 text-muted-foreground">
          到期时间 {{ formatDateTime(share.expires_at) }}。可在 设置 → 分享链接 里随时撤销。
        </p>

        <DialogFooter class="mt-4">
          <Button class="h-9" variant="outline" @click="copy">
            <Check v-if="copied" class="size-4" />
            <Copy v-else class="size-4" />
            <span>{{ copied ? '已复制' : '复制链接' }}</span>
          </Button>
        </DialogFooter>
      </template>
    </DialogContent>
  </Dialog>
</template>
