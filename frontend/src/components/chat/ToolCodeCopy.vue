<script setup lang="ts">
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import { Check, Copy } from '@lucide/vue'

import { TooltipHint } from '@/components/ui/tooltip'

const props = defineProps<{ code: string }>()
const { copied, copyText } = useCopyFeedback()

async function copy(): Promise<void> {
  await copyText(props.code)
}
</script>

<template>
  <TooltipHint :text="copied ? '已复制' : '复制'">
    <button
      type="button"
      class="inline-flex h-6 shrink-0 items-center gap-1 rounded px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-surface-strong hover:text-foreground"
      :aria-label="copied ? '已复制' : '复制代码'"
      @click="copy"
    >
      <Check v-if="copied" class="size-3" />
      <Copy v-else class="size-3" />
      <span>{{ copied ? '已复制' : '复制' }}</span>
    </button>
  </TooltipHint>
</template>
