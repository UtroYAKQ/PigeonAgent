<script setup lang="ts">
import { computed } from 'vue'

import LlmModelIcon from '@/components/chat/LlmModelIcon.vue'
import { TooltipHint } from '@/components/ui/tooltip'
import { LLM_ICONS } from '@/lib/llmIcons'

const icon = defineModel<string>({ required: true })

const selectedLabel = computed(() => {
  if (!icon.value) return '不设置（显示名称首字母）'
  return LLM_ICONS.find(item => item.key === icon.value)?.label ?? icon.value
})
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-sm font-medium">图标</span>
      <span class="truncate text-xs text-muted-foreground">{{ selectedLabel }}</span>
    </div>
    <div class="grid grid-cols-8 gap-1.5 sm:grid-cols-11">
      <TooltipHint text="不设置图标">
        <button
          type="button"
          class="grid h-9 place-items-center rounded-md border text-xs transition-colors"
          :class="icon
            ? 'border-border text-muted-foreground hover:bg-muted'
            : 'border-foreground/25 bg-muted text-foreground'"
          aria-label="不设置图标"
          @click="icon = ''"
        >
          无
        </button>
      </TooltipHint>
      <TooltipHint
        v-for="item in LLM_ICONS"
        :key="item.key"
        :text="item.label"
      >
        <button
          type="button"
          class="grid h-9 place-items-center rounded-md border transition-colors"
          :class="icon === item.key
            ? 'border-foreground/25 bg-muted'
            : 'border-border hover:bg-muted'"
          :aria-pressed="icon === item.key"
          :aria-label="item.label"
          @click="icon = item.key"
        >
          <LlmModelIcon :icon="item.key" :size="20" />
        </button>
      </TooltipHint>
    </div>
  </div>
</template>
