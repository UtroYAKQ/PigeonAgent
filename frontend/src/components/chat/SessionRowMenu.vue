<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { Archive, ArchiveRestore, FolderInput, MoreHorizontal, Pencil, Trash2 } from '@lucide/vue'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { errorMessage } from '@/lib/http'
import { formatTokens } from '@/lib/format'
import { useChatStore } from '@/stores/chat'
import type { ChatSession } from '@/types/api'

const props = defineProps<{ session: ChatSession }>()
const emit = defineEmits<{
  rename: [session: ChatSession]
  delete: [session: ChatSession]
}>()

const chat = useChatStore()
const router = useRouter()
const route = useRoute()

const isArchived = computed(() => props.session.status === 'archived')
const isBusyCurrent = computed(() => chat.busy && route.params.id === props.session.id)
const totalTokens = computed(() => props.session.usage?.total_tokens ?? 0)

async function toggleArchive(): Promise<void> {
  try {
    if (isArchived.value) {
      await chat.unarchiveSession(props.session)
      toast.success('已取消归档')
    } else {
      await chat.archiveSession(props.session)
      toast.success('对话已归档')
      if (route.params.id === props.session.id) await router.push('/chat')
    }
  } catch (error) {
    toast.error('操作失败', { description: errorMessage(error) })
  }
}

async function move(groupId: number | null): Promise<void> {
  try {
    await chat.moveSessionToGroup(props.session, groupId)
  } catch (error) {
    toast.error('移动失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button
        type="button"
        class="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground opacity-100 transition-opacity hover:bg-sidebar-accent sm:opacity-0 sm:group-hover/session:opacity-100 sm:focus-visible:opacity-100"
        aria-label="对话操作"
        @click.stop
      >
        <MoreHorizontal class="size-3.5" />
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" class="w-[224px] rounded-xl p-1.5" @click.stop>
      <template v-if="totalTokens">
        <div class="mx-0.5 mb-1 rounded-lg bg-muted/45 px-2.5 py-2.5">
          <div class="flex items-baseline justify-between gap-3">
            <span class="text-[11px] text-muted-foreground">本会话用量</span>
            <span class="text-[13px] font-semibold tabular-nums">
              {{ formatTokens(totalTokens) }}<span class="ml-1 text-[10px] font-normal text-muted-foreground">tokens</span>
            </span>
          </div>
          <div class="mt-2.5 grid grid-cols-3 gap-2 border-t border-border/70 pt-2">
            <div>
              <p class="text-[10px] text-muted-foreground">输入</p>
              <p class="mt-0.5 text-[11.5px] font-medium tabular-nums">{{ formatTokens(session.usage.input_tokens) }}</p>
            </div>
            <div>
              <p class="text-[10px] text-muted-foreground">输出</p>
              <p class="mt-0.5 text-[11.5px] font-medium tabular-nums">{{ formatTokens(session.usage.output_tokens) }}</p>
            </div>
            <div>
              <p class="text-[10px] text-muted-foreground">其中缓存</p>
              <p class="mt-0.5 text-[11.5px] font-medium tabular-nums">{{ formatTokens(session.usage.cache_read_tokens) }}</p>
            </div>
          </div>
        </div>
        <DropdownMenuSeparator />
      </template>

      <template v-if="!isArchived">
        <DropdownMenuItem class="cursor-pointer rounded-lg text-[13px]" @select="emit('rename', session)">
          <Pencil class="mr-2 size-3.5" />
          重命名
        </DropdownMenuItem>

        <DropdownMenuSub>
          <DropdownMenuSubTrigger class="rounded-lg text-[13px]">
            <FolderInput class="mr-2 size-3.5" />
            移动到分组
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent class="w-[180px] rounded-xl p-1.5">
            <DropdownMenuItem
              class="cursor-pointer rounded-lg text-[13px]"
              :disabled="session.group_id == null"
              @select="move(null)"
            >
              不放入分组
            </DropdownMenuItem>
            <DropdownMenuItem
              v-for="group in chat.groups"
              :key="group.id"
              class="cursor-pointer rounded-lg text-[13px]"
              :disabled="session.group_id === group.id"
              @select="move(group.id)"
            >
              {{ group.name }}
            </DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        <DropdownMenuItem class="cursor-pointer rounded-lg text-[13px]" :disabled="isBusyCurrent" @select="toggleArchive">
          <Archive class="mr-2 size-3.5" />
          归档
        </DropdownMenuItem>
        <DropdownMenuSeparator />
      </template>

      <template v-else>
        <DropdownMenuItem class="cursor-pointer rounded-lg text-[13px]" :disabled="isBusyCurrent" @select="toggleArchive">
          <ArchiveRestore class="mr-2 size-3.5" />
          取消归档
        </DropdownMenuItem>
        <DropdownMenuSeparator />
      </template>

      <DropdownMenuItem
        class="cursor-pointer rounded-lg text-[13px] text-destructive focus:text-destructive"
        :disabled="isBusyCurrent"
        @select="emit('delete', session)"
      >
        <Trash2 class="mr-2 size-3.5" />
        删除对话
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
