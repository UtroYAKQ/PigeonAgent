<script setup lang="ts">
import { computed } from 'vue'

import { TooltipHint } from '@/components/ui/tooltip'

/**
 * 输入框下方的能力开关。
 *
 * 只留图标：移动端一行要放模型、附件、联网、图片、挡位、语音和发送，
 * 每个开关再带一条滑轨就会把输入框挤爆。开没开由底色和图标色表达，
 * 文字只在 sm 以上出现。
 */
const props = defineProps<{
  active: boolean
  label: string
}>()

const emit = defineEmits<{ toggle: [] }>()

const hint = computed(() => `${props.label}：${props.active ? '已开启，点击关闭' : '已关闭，点击开启'}`)
</script>

<template>
  <TooltipHint :text="hint">
    <button
      type="button"
      class="inline-flex h-7 items-center gap-1.5 rounded-full px-2 text-[11.5px] transition-colors"
      :class="active
        ? 'bg-brand-soft text-brand'
        : 'text-muted-foreground hover:bg-surface hover:text-foreground'"
      :aria-pressed="active"
      :aria-label="label"
      @click="emit('toggle')"
    >
      <slot />
      <span class="hidden sm:inline">{{ label }}</span>
    </button>
  </TooltipHint>
</template>
