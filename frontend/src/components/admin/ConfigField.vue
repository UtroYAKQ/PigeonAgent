<script setup lang="ts">
import { computed, ref } from 'vue'
import { Eye, EyeOff } from '@lucide/vue'

import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { AppConfigItem } from '@/types/api'

const props = defineProps<{ item: AppConfigItem }>()
// type="number" 的输入框由 Vue 自动转成 number，所以这里两种都得认
const draft = defineModel<string | number>({ required: true })

const reveal = ref(false)
const enabled = computed(() => draft.value === 'true')

/**
 * 只在「看不出来」的时候才提示：密钥不回显，得说明有没有配过。
 * 整数/数字/可选值这类类型说明纯属噪音——控件本身就长那样，开关的状态也一眼可见。
 */
const hint = computed(() => {
  if (props.item.is_secret) return props.item.has_value ? '已配置' : '未配置'
  return null
})

function toggle(): void {
  draft.value = enabled.value ? 'false' : 'true'
}
</script>

<template>
  <div class="grid gap-3 border-t border-border py-4 first:border-t-0 md:grid-cols-[minmax(0,1fr)_300px] md:items-start md:gap-10">
    <div class="min-w-0">
      <label :for="`config-${item.key}`" class="text-sm font-medium leading-5">
        {{ item.label }}
      </label>
      <p v-if="item.description" class="mt-1 max-w-[60ch] text-sm leading-6 text-muted-foreground">
        {{ item.description }}
      </p>
    </div>

    <div class="min-w-0">
      <Switch
        v-if="item.value_type === 'bool'"
        :id="`config-${item.key}`"
        :model-value="enabled"
        :aria-label="item.label"
        @update:model-value="toggle"
      />

      <Select v-else-if="item.choices?.length" v-model="draft">
        <SelectTrigger :id="`config-${item.key}`" class="h-9 w-full text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" class="w-[var(--reka-select-trigger-width)]">
          <SelectItem
            v-for="choice in item.choices"
            :key="choice"
            :value="choice"
            class="text-[13px]"
          >
            {{ choice }}
          </SelectItem>
        </SelectContent>
      </Select>

      <div v-else-if="item.is_secret" class="relative">
        <Input
          :id="`config-${item.key}`"
          v-model="draft"
          :type="reveal ? 'text' : 'password'"
          :placeholder="item.has_value ? '已配置 · 输入新值以替换' : '未配置'"
          autocomplete="off"
          spellcheck="false"
          class="h-9 pr-9 text-sm"
        />
        <button
          type="button"
          class="absolute right-1 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          :aria-label="reveal ? '隐藏内容' : '显示内容'"
          @click="reveal = !reveal"
        >
          <EyeOff v-if="reveal" class="size-3.5" />
          <Eye v-else class="size-3.5" />
        </button>
      </div>

      <Input
        v-else-if="item.value_type === 'int' || item.value_type === 'float'"
        :id="`config-${item.key}`"
        v-model="draft"
        type="number"
        :step="item.value_type === 'int' ? 1 : 'any'"
        class="h-9 text-sm"
      />

      <Input
        v-else
        :id="`config-${item.key}`"
        v-model="draft"
        type="text"
        spellcheck="false"
        placeholder="未设置"
        class="h-9 text-sm"
      />

      <span class="mt-2 flex h-5 items-center truncate text-xs text-muted-foreground">{{ hint }}</span>
    </div>
  </div>
</template>
