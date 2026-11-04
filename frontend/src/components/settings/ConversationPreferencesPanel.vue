<script setup lang="ts">
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Switch } from '@/components/ui/switch'
import { useUiStore } from '@/stores/ui'

type PreferenceKey = 'autoExpandThinking' | 'autoExpandToolDetails' | 'wrapCode'

interface PreferenceOption {
  key: PreferenceKey
  label: string
  description: string
}

const ui = useUiStore()

const OPTIONS: PreferenceOption[] = [
  {
    key: 'autoExpandThinking',
    label: '展开思考过程',
    description: '历史消息中的思考过程默认展开；正在生成的回复仍会自动展开。',
  },
  {
    key: 'autoExpandToolDetails',
    label: '展开工具详情',
    description: '工具调用的参数与输出默认展开，便于查看命令和结果。',
  },
  {
    key: 'wrapCode',
    label: '代码块自动换行',
    description: '长代码不再横向滚动，按消息宽度自动折行。',
  },
]

function apply(key: PreferenceKey, value: boolean): void {
  if (key === 'autoExpandThinking') ui.setAutoExpandThinking(value)
  else if (key === 'autoExpandToolDetails') ui.setAutoExpandToolDetails(value)
  else ui.setWrapCode(value)
}
</script>

<template>
  <div class="pt-3">
    <ConsoleSection
      title="显示"
      description="只影响你的阅读方式，不会改变模型输出；修改后立即生效并保存到账号。"
    >
      <div class="space-y-5">
        <div
          v-for="option in OPTIONS"
          :key="option.key"
          class="flex items-start justify-between gap-8"
        >
          <div class="min-w-0">
            <p class="text-sm font-medium">{{ option.label }}</p>
            <p class="mt-1 max-w-[60ch] text-sm leading-6 text-muted-foreground">
              {{ option.description }}
            </p>
          </div>
          <Switch
            :model-value="ui[option.key]"
            :aria-label="option.label"
            class="mt-0.5 shrink-0"
            @update:model-value="value => apply(option.key, value)"
          />
        </div>
      </div>
    </ConsoleSection>
  </div>
</template>
