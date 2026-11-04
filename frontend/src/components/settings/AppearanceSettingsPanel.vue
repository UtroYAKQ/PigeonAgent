<script setup lang="ts">
import { type Component } from 'vue'
import { Check, Monitor, Moon, Sun } from '@lucide/vue'

import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { useUiStore, type ThemePreference } from '@/stores/ui'

const THEME_OPTIONS: {
  value: ThemePreference
  label: string
  description: string
  icon: Component
}[] = [
  { value: 'light', label: '浅色', description: '白色纸面，适合明亮环境', icon: Sun },
  { value: 'dark', label: '深色', description: '降低亮度，适合夜间使用', icon: Moon },
  { value: 'system', label: '跟随系统', description: '随系统的深浅色设置切换', icon: Monitor },
]

const ui = useUiStore()
</script>

<template>
  <div class="pt-3">
    <ConsoleSection
      title="主题"
      description="界面会立即切换，并同步到当前账号。"
    >
      <div class="grid gap-3 sm:grid-cols-3">
        <button
          v-for="option in THEME_OPTIONS"
          :key="option.value"
          type="button"
          class="rounded-lg border p-1.5 text-left transition-colors"
          :class="ui.theme === option.value
            ? 'border-foreground/20 bg-muted/50'
            : 'border-border bg-card hover:bg-muted/30'"
          :aria-pressed="ui.theme === option.value"
          @click="ui.setTheme(option.value)"
        >
          <span class="theme-preview relative block h-[104px] overflow-hidden rounded-md border border-border" :data-theme="option.value">
            <span class="flex h-full">
              <span class="theme-preview__rail w-[34%] border-r p-2.5">
                <span class="block h-1.5 w-7 rounded-full bg-current opacity-30" />
                <span class="mt-2.5 block h-1 w-full rounded-full bg-current opacity-15" />
                <span class="mt-1.5 block h-1 w-4/5 rounded-full bg-current opacity-15" />
                <span class="mt-1.5 block h-1 w-3/5 rounded-full bg-current opacity-15" />
              </span>
              <span class="flex-1 p-3">
                <span class="block h-2 w-12 rounded-full bg-current opacity-25" />
                <span class="mt-2 block h-1 w-4/5 rounded-full bg-current opacity-15" />
                <span class="mt-1.5 block h-1 w-3/5 rounded-full bg-current opacity-15" />
                <span class="mt-3 block h-5 w-full rounded-md border border-current opacity-[0.08]" />
              </span>
            </span>
            <span
              v-if="option.value === 'system'"
              class="absolute inset-y-0 right-0 w-1/2 border-l border-white/10 bg-[#212121] p-3 text-[#ececec]"
            >
              <span class="block h-2 w-9 rounded-full bg-current opacity-25" />
              <span class="mt-2 block h-1 w-4/5 rounded-full bg-current opacity-15" />
              <span class="mt-1.5 block h-1 w-3/5 rounded-full bg-current opacity-15" />
            </span>
          </span>
          <span class="mt-2.5 flex items-center justify-between gap-2 px-1">
            <span class="inline-flex items-center gap-2 text-[13px] font-medium">
              <component :is="option.icon" class="size-3.5 text-muted-foreground" :stroke-width="1.8" />
              {{ option.label }}
            </span>
            <Check v-if="ui.theme === option.value" class="size-3.5 shrink-0" />
            <span v-else class="size-3.5 shrink-0" />
          </span>
          <span class="mt-0.5 block px-1 pb-0.5 text-xs leading-5 text-muted-foreground">
            {{ option.description }}
          </span>
        </button>
      </div>
    </ConsoleSection>
  </div>
</template>

<style scoped>
.theme-preview {
  --preview-bg: #ffffff;
  --preview-fg: #0d0d0d;
  --preview-rail: #f7f7f8;
  --preview-line: rgba(13, 13, 13, 0.08);
  background: var(--preview-bg);
  color: var(--preview-fg);
}

.theme-preview[data-theme='dark'] {
  --preview-bg: #212121;
  --preview-fg: #ececec;
  --preview-rail: #1b1b1b;
  --preview-line: rgba(255, 255, 255, 0.09);
}

.theme-preview[data-theme='system'] {
  background: linear-gradient(90deg, #ffffff 50%, #212121 50%);
  --preview-rail: #f7f7f8;
  --preview-line: rgba(13, 13, 13, 0.08);
}

.theme-preview__rail {
  background: var(--preview-rail);
  border-color: var(--preview-line);
}
</style>
