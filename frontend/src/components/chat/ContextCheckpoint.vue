<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, Layers } from '@lucide/vue'

import { formatTokens } from '@/lib/format'
import MarkdownMessage from './MarkdownMessage.vue'

const props = defineProps<{
  state: 'running' | 'done'
  summary?: string | null
  tokensBefore?: number | null
}>()

const open = ref(false)
const hasSummary = computed(() => Boolean(props.summary?.trim()))
const label = computed(() => (props.state === 'running' ? '正在压缩上下文' : '上下文已压缩'))
</script>

<template>
  <div class="not-prose">
    <div class="flex items-center gap-3 py-1">
      <span class="h-px flex-1 bg-border/80" aria-hidden="true" />
      <button
        v-if="hasSummary"
        type="button"
        class="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[12px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
        :aria-expanded="open"
        :aria-label="open ? '收起上下文摘要' : '查看上下文摘要'"
        @click="open = !open"
      >
        <Layers class="size-3" :stroke-width="1.8" />
        <span>{{ label }}</span>
        <span v-if="tokensBefore" class="font-mono tabular-nums">· {{ formatTokens(tokensBefore) }} tokens</span>
        <ChevronDown
          class="size-3 transition-transform duration-150"
          :class="open ? 'rotate-180' : ''"
        />
      </button>
      <span
        v-else
        class="inline-flex items-center gap-1.5 px-2 py-1 text-[12px] text-muted-foreground"
      >
        <Layers
          class="size-3"
          :class="state === 'running' ? 'animate-pulse motion-reduce:animate-none' : ''"
          :stroke-width="1.8"
        />
        <span>{{ label }}</span>
        <span v-if="tokensBefore" class="font-mono tabular-nums">· 约 {{ formatTokens(tokensBefore) }} tokens</span>
      </span>
      <span class="h-px flex-1 bg-border/80" aria-hidden="true" />
    </div>

    <div
      v-if="open && hasSummary"
      class="context-summary mt-2 max-h-[320px] overflow-y-auto rounded-xl border border-border/70 bg-surface/50 px-4 py-3"
    >
      <MarkdownMessage :content="summary ?? ''" />
    </div>
  </div>
</template>

<style scoped>
.context-summary :deep(.markdown) {
  font-size: 13.5px;
  line-height: 1.72;
  color: var(--muted-foreground);
}

.context-summary :deep(.markdown h1),
.context-summary :deep(.markdown h2),
.context-summary :deep(.markdown h3),
.context-summary :deep(.markdown h4) {
  margin: 0 0 0.45em;
  color: var(--muted-foreground);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0;
  line-height: 1.4;
}

.context-summary :deep(.markdown p) {
  margin: 0.4em 0;
}

.context-summary :deep(.markdown ul),
.context-summary :deep(.markdown ol) {
  margin: 0.4em 0;
  padding-left: 1.25em;
}

.context-summary :deep(.markdown li) {
  margin: 0.2em 0;
}

.context-summary :deep(.markdown > *:first-child) {
  margin-top: 0;
}

.context-summary :deep(.markdown > *:last-child) {
  margin-bottom: 0;
}
</style>
