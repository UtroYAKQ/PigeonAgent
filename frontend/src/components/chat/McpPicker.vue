<script setup lang="ts">
import { computed } from 'vue'
import { toast } from 'vue-sonner'
import { Plug } from '@lucide/vue'

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useChatStore } from '@/stores/chat'
import { errorMessage } from '@/lib/http'
import type { McpServerOption } from '@/types/api'

const chat = useChatStore()
const selected = computed(() => new Set(chat.selectedMcpServerIds))
const selectedCount = computed(
  () => chat.mcpServers.filter(server => selected.value.has(server.id)).length,
)
const locked = computed(() => chat.busy || Boolean(chat.currentSession?.pending_batches))

async function toggle(server: McpServerOption, value: boolean): Promise<void> {
  try {
    await chat.setMcpServerEnabled(server.id, value)
  } catch (error) {
    toast.error('修改 MCP 选择失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button
        type="button"
        class="inline-flex h-7 items-center gap-1.5 rounded-full px-2 text-[11.5px] transition-colors"
        :class="selectedCount
          ? 'bg-brand-soft text-brand'
          : 'text-muted-foreground hover:bg-surface hover:text-foreground'"
        :disabled="locked"
        :aria-label="`MCP 服务器：已启用 ${selectedCount} 个`"
      >
        <Plug class="size-3.5" :stroke-width="1.8" />
        <span class="hidden sm:inline">MCP</span>
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" class="w-72">
      <DropdownMenuLabel>本会话启用的 MCP</DropdownMenuLabel>
      <p class="px-2 pb-1 text-[11px] text-muted-foreground">
        最多 {{ chat.maxMcpServers }} 个；勾选后模型可调用对应服务器的工具。
      </p>
      <DropdownMenuSeparator />
      <DropdownMenuCheckboxItem
        v-for="server in chat.mcpServers"
        :key="server.id"
        :model-value="selected.has(server.id)"
        :disabled="locked"
        class="items-start"
        @update:model-value="value => toggle(server, Boolean(value))"
      >
        <span class="min-w-0">
          <span class="flex items-center gap-1.5">
            <span class="truncate text-[13px]">{{ server.name }}</span>
            <span
              v-if="server.requires_approval"
              class="shrink-0 rounded border border-border px-1 text-[10px] text-muted-foreground"
            >需确认</span>
          </span>
          <span class="mt-0.5 block truncate text-[11px] text-muted-foreground">
            {{ server.description || server.slug }} · {{ server.tool_count }} 个工具
          </span>
        </span>
      </DropdownMenuCheckboxItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
