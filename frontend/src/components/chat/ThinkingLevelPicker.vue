<script setup lang="ts">
import { computed } from 'vue'
import { toast } from 'vue-sonner'
import { Brain, Check } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { errorMessage } from '@/lib/http'
import { THINKING_LABELS } from '@/lib/modelOptions'
import { useChatStore } from '@/stores/chat'
import type { ThinkingLevel } from '@/types/api'

const chat = useChatStore()

const label = computed(() => {
  const level = chat.currentThinkingLevel
  return level ? THINKING_LABELS[level] : '默认'
})

async function choose(level: ThinkingLevel | null): Promise<void> {
  if (level === chat.currentThinkingLevel) return
  try {
    await chat.setThinkingLevel(level)
  } catch (error) {
    toast.error('切换思考挡位失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <DropdownMenu v-if="chat.thinkingLevels.length">
    <DropdownMenuTrigger as-child>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        class="h-7 max-w-[96px] gap-1.5 rounded-full px-2 text-[12px] font-medium text-muted-foreground hover:bg-surface hover:text-foreground sm:max-w-[110px] sm:px-2.5"
        :title="`思考挡位：${label}`"
        :aria-label="`思考挡位：${label}`"
      >
        <Brain class="size-3.5" :stroke-width="1.8" />
        <span class="hidden truncate sm:inline">{{ label }}</span>
      </Button>
    </DropdownMenuTrigger>

    <DropdownMenuContent align="end" side="bottom" :collision-padding="10" class="w-36 rounded-xl p-1 sm:w-40 sm:p-1.5">
      <DropdownMenuLabel class="px-2 py-1.5 text-[11.5px] font-medium text-muted-foreground sm:px-2.5 sm:text-[12px]">
        思考挡位
      </DropdownMenuLabel>
      <DropdownMenuItem class="cursor-pointer rounded-lg px-2 py-1.5 sm:px-2.5 sm:py-2" @select="choose(null)">
        <span class="grid size-4 shrink-0 place-items-center">
          <Check v-if="!chat.currentThinkingLevel" class="size-3.5" :stroke-width="2.2" />
        </span>
        <span class="ml-2 text-[12.5px] sm:text-[13px]">默认</span>
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        v-for="level in chat.thinkingLevels"
        :key="level"
        class="cursor-pointer rounded-lg px-2 py-1.5 sm:px-2.5 sm:py-2"
        @select="choose(level)"
      >
        <span class="grid size-4 shrink-0 place-items-center">
          <Check v-if="chat.currentThinkingLevel === level" class="size-3.5" :stroke-width="2.2" />
        </span>
        <span class="ml-2 text-[12.5px] sm:text-[13px]">{{ THINKING_LABELS[level] }}</span>
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
