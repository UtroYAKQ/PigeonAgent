<script setup lang="ts">
import { computed } from 'vue'

import { TooltipHint } from '@/components/ui/tooltip'
import { findLlmIcon } from '@/lib/llmIcons'

const props = withDefaults(defineProps<{
  icon?: string | null
  name?: string
  size?: number
}>(), {
  icon: null,
  name: '',
  size: 16,
})

const resolved = computed(() => findLlmIcon(props.icon))
const fallback = computed(() => (props.name.trim().slice(0, 1) || '·').toUpperCase())
const chipStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.max(9, Math.round(props.size * 0.42))}px`,
}))
</script>

<template>
  <TooltipHint v-if="resolved" :text="resolved.label">
    <img
      :src="resolved.url"
      :alt="resolved.label"
      draggable="false"
      class="shrink-0 select-none object-contain"
      :class="resolved.mono ? 'dark:invert' : ''"
      :style="{ width: `${size}px`, height: `${size}px` }"
    >
  </TooltipHint>
  <span
    v-else
    class="grid shrink-0 select-none place-items-center rounded-md border border-border bg-background font-mono leading-none text-muted-foreground"
    :style="chipStyle"
  >
    {{ fallback }}
  </span>
</template>
