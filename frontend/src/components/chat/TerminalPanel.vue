<script setup lang="ts">
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import { Check, Copy } from '@lucide/vue'

const props = defineProps<{
  stdout: string
  stderr?: string
  exitCode?: number | null
}>()

const { copied, copyText } = useCopyFeedback()

async function copy(): Promise<void> {
  await copyText(props.stdout)
}
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-border bg-code text-foreground">
    <div class="flex h-8 items-center justify-between border-b border-border px-3">
      <span class="font-mono text-[11px] text-muted-foreground">output</span>
      <div class="flex items-center gap-2">
        <span v-if="exitCode != null" class="font-mono text-[10.5px]" :class="exitCode === 0 ? 'text-brand' : 'text-destructive'">
          exit {{ exitCode }}
        </span>
        <button
          type="button"
          class="inline-flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-surface-strong hover:text-foreground"
          aria-label="复制输出"
          @click="copy"
        >
          <Check v-if="copied" class="size-3" />
          <Copy v-else class="size-3" />
          <span>{{ copied ? '已复制' : '复制' }}</span>
        </button>
      </div>
    </div>
    <pre class="max-h-[320px] overflow-auto whitespace-pre-wrap break-words px-3.5 py-3 font-mono text-[12.3px] leading-[1.65]">{{ stdout || '（无输出）' }}</pre>
    <div v-if="stderr" class="border-t border-border px-3.5 py-2.5">
      <p class="mb-1 font-mono text-[10.5px] text-destructive">stderr</p>
      <pre class="max-h-[200px] overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.6] text-destructive/85">{{ stderr }}</pre>
    </div>
  </div>
</template>
