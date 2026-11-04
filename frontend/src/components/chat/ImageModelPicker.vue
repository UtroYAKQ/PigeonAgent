<script setup lang="ts">
import { computed } from 'vue'
import { Image as ImageIcon } from '@lucide/vue'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useChatStore } from '@/stores/chat'
import LlmModelIcon from './LlmModelIcon.vue'

const chat = useChatStore()

const active = computed(() => chat.effectiveImageGeneration)
const selected = computed(() => chat.currentImageModel)
const label = computed(() => (active.value ? selected.value?.name ?? '图片' : '图片'))

/** 再点一次当前模型就关掉，不再单独占一行「关闭」。 */
function choose(id: number): void {
  chat.setImageModel(active.value && selected.value?.id === id ? null : id)
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button
        type="button"
        class="inline-flex h-7 max-w-[130px] items-center gap-1.5 rounded-full px-2 text-[11.5px] transition-colors sm:max-w-[150px]"
        :class="active
          ? 'bg-brand-soft text-brand'
          : 'text-muted-foreground hover:bg-surface hover:text-foreground'"
        :aria-label="`图片模型：${label}`"
        :title="`图片模型：${label}`"
      >
        <ImageIcon class="size-3.5 shrink-0" :stroke-width="1.8" />
        <span class="hidden truncate sm:inline">{{ label }}</span>
      </button>
    </DropdownMenuTrigger>

    <DropdownMenuContent align="start" side="bottom" :collision-padding="10" class="w-[248px] rounded-xl p-1.5">
      <DropdownMenuLabel class="px-2 py-1.5 text-[11.5px] font-medium text-muted-foreground">
        图片生成
      </DropdownMenuLabel>
      <DropdownMenuItem
        v-for="model in chat.imageModels"
        :key="model.id"
        class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5"
        @select="choose(model.id)"
      >
        <span class="grid size-4 shrink-0 place-items-center">
          <span
            v-if="active && selected?.id === model.id"
            class="size-1.5 rounded-full bg-current"
            aria-hidden="true"
          />
        </span>
        <LlmModelIcon :icon="model.icon" :name="model.name" :size="18" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[13px] leading-[18px] text-foreground">{{ model.name }}</span>
          <span class="block truncate text-[11px] leading-4 text-muted-foreground">
            {{ model.default_size }} · 最多 {{ model.max_images }} 张
          </span>
        </span>
        <span
          v-if="model.is_default"
          class="rounded-full border border-border px-1.5 py-0.5 text-[10.5px] leading-3 text-muted-foreground"
        >
          默认
        </span>
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
