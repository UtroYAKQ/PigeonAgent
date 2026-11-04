<script setup lang="ts">
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { useUiStore, type SendShortcut } from '@/stores/ui'

const ui = useUiStore()

const OPTIONS: { value: SendShortcut; label: string }[] = [
  { value: 'enter', label: 'Enter 发送' },
  { value: 'ctrl-enter', label: 'Ctrl + Enter 发送' },
]

function apply(value: SendShortcut): void {
  ui.setSendShortcut(value)
}
</script>

<template>
  <div class="pt-3">
    <ConsoleSection
      title="输入"
      description="选择直接按 Enter 发送，或使用 Ctrl / ⌘ + Enter 发送；Shift + Enter 始终换行。修改后立即生效并保存到账号。"
    >
      <div class="flex flex-wrap items-center justify-between gap-4">
        <p class="text-sm font-medium">发送快捷键</p>
        <div class="flex w-fit rounded-lg bg-muted p-1" role="group" aria-label="发送快捷键">
          <button
            v-for="option in OPTIONS"
            :key="option.value"
            type="button"
            class="h-8 rounded-md px-3 text-sm transition-colors"
            :class="ui.sendShortcut === option.value
              ? 'bg-background font-medium text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'"
            :aria-pressed="ui.sendShortcut === option.value"
            @click="apply(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
    </ConsoleSection>
  </div>
</template>
