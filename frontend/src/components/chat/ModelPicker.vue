<script setup lang="ts">
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Check, Cpu, Loader2 } from '@lucide/vue'

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
import { useChatStore } from '@/stores/chat'
import LlmModelIcon from './LlmModelIcon.vue'

const chat = useChatStore()
const switching = ref(false)

const selected = computed(() => chat.currentModel)
const label = computed(() => selected.value?.name ?? (chat.modelsLoaded ? '未配置模型' : '加载模型'))

async function choose(id: number): Promise<void> {
  if (id === chat.currentModelId || switching.value) return
  switching.value = true
  try {
    await chat.updateSessionModel(id)
  } catch (error) {
    toast.error('切换模型失败', { description: errorMessage(error) })
  } finally {
    switching.value = false
  }
}

async function refresh(): Promise<void> {
  try {
    await chat.refreshModels()
    toast.success('模型列表已更新')
  } catch (error) {
    toast.error('刷新失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="sm"
        class="h-7 max-w-[150px] gap-1.5 rounded-full px-2 text-[12px] font-medium text-muted-foreground hover:bg-surface hover:text-foreground sm:h-8 sm:max-w-[210px] sm:px-2.5"
        :disabled="chat.busy"
        :aria-label="`模型：${label}`"
      >
        <Loader2 v-if="switching" class="size-3.5 animate-spin" />
        <LlmModelIcon v-else-if="selected" :icon="selected.icon" :name="selected.name" :size="16" />
        <Cpu v-else class="size-3.5" :stroke-width="1.8" />
        <span class="hidden truncate sm:inline">{{ label }}</span>
      </Button>
    </DropdownMenuTrigger>

    <DropdownMenuContent align="end" :collision-padding="10" class="w-[224px] rounded-xl p-1 sm:w-[280px] sm:p-1.5">
      <DropdownMenuLabel class="px-2 py-1.5 text-[11.5px] font-medium text-muted-foreground sm:px-2.5 sm:py-2 sm:text-[12px]">
        选择模型
      </DropdownMenuLabel>

      <DropdownMenuItem
        v-for="model in chat.activeModels"
        :key="model.id"
        class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 sm:items-start sm:gap-2.5 sm:px-2.5 sm:py-2"
        @select="choose(model.id)"
      >
        <div class="grid size-4 shrink-0 place-items-center sm:mt-1">
          <Check v-if="model.id === chat.currentModelId" class="size-3.5" :stroke-width="2.2" />
        </div>
        <LlmModelIcon :icon="model.icon" :name="model.name" :size="20" class="sm:mt-0.5" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-[13px] leading-[18px] text-foreground sm:text-[13.5px] sm:leading-5">{{ model.name }}</p>
          <p class="hidden truncate text-[11px] leading-4 text-muted-foreground sm:block sm:text-[11.5px]">
            {{ model.provider }}<span v-if="model.model_name"> · {{ model.model_name }}</span>
          </p>
        </div>
        <span
          v-if="model.is_default"
          class="rounded-full border border-border px-1.5 py-0.5 text-[10.5px] leading-3 text-muted-foreground sm:mt-0.5"
        >
          默认
        </span>
      </DropdownMenuItem>

      <p v-if="!chat.activeModels.length" class="px-2 py-2.5 text-[12.5px] leading-5 text-muted-foreground sm:px-2.5 sm:py-3 sm:text-[13px]">
        管理员还没有配置可用模型。
      </p>

      <DropdownMenuSeparator />
      <DropdownMenuItem class="cursor-pointer rounded-lg px-2 py-1.5 text-[12.5px] text-muted-foreground sm:px-2.5 sm:py-2 sm:text-[13px]" @select="refresh">
        刷新模型列表
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
