<script setup lang="ts">
import { CircleSlash } from '@lucide/vue'

defineProps<{ sourceKind: string }>()
</script>

<template>
  <div class="my-3 flex items-start gap-2 rounded-lg border border-border bg-surface/50 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
    <CircleSlash class="mt-0.5 size-3.5 shrink-0" />
    <span class="min-w-0 flex-1">暂不支持的内容类型：{{ sourceKind }}</span>
  </div>
</template>