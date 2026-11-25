<script setup lang="ts">
import { computed } from 'vue'
import { LayoutPanelTop } from '@lucide/vue'

const props = defineProps<{
  renderer: string
  data: unknown
}>()

const text = computed(() => {
  if (typeof props.data === 'string') return props.data
  try {
    return JSON.stringify(props.data, null, 2)
  } catch {
    return String(props.data)
  }
})
</script>

<template>
  <div class="my-3 rounded-xl border border-border bg-surface/50 px-4 py-3">
    <details>
      <summary class="flex cursor-pointer items-center gap-2 text-[12px] leading-5 text-muted-foreground">
        <LayoutPanelTop class="size-3.5 shrink-0" :stroke-width="1.8" />
        自定义内容 · {{ renderer }}
      </summary>
      <pre class="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words font-mono text-[11.5px] leading-5 text-muted-foreground">{{ text }}</pre>
    </details>
  </div>
</template>