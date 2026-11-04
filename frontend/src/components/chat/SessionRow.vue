<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import type { ChatSession, UUID } from '@/types/api'
import SessionRowMenu from './SessionRowMenu.vue'
import SonarDot from './SonarDot.vue'
import { TooltipHint } from '@/components/ui/tooltip'

const props = defineProps<{
  session: ChatSession
  active: boolean
  /** 分组内的会话多一层缩进 */
  indented?: boolean
}>()

const emit = defineEmits<{
  open: [session: ChatSession]
  rename: [session: ChatSession]
  delete: [session: ChatSession]
}>()

const chat = useChatStore()

function isActive(id: UUID): boolean {
  return chat.currentSessionId === id
}
</script>

<template>
  <div
    class="group/session relative flex h-9 items-center rounded-md border border-transparent pr-1 transition-colors"
    :class="props.active || isActive(session.id) ? 'border-sidebar-border bg-background' : 'hover:bg-sidebar-accent/60'"
  >
    <button
      type="button"
      class="flex h-full min-w-0 flex-1 items-center pr-1 text-left"
      :class="props.indented ? 'pl-6' : 'pl-2.5'"
      @click="emit('open', session)"
    >
      <span
        class="truncate text-[13.5px] leading-5 text-sidebar-foreground"
        :class="isActive(session.id) || session.has_unread ? 'font-medium' : ''"
      >
        {{ session.title || '未命名对话' }}
      </span>
    </button>
    <TooltipHint v-if="session.active_run_id || (chat.busy && isActive(session.id))" text="正在生成">
      <SonarDot :size="5" class="mr-1" />
    </TooltipHint>
    <TooltipHint v-else-if="session.has_unread && !isActive(session.id)" text="未读">
      <span class="mr-1.5 size-1.5 shrink-0 rounded-full bg-foreground" aria-label="未读" />
    </TooltipHint>
    <SessionRowMenu :session="session" @rename="emit('rename', $event)" @delete="emit('delete', $event)" />
  </div>
</template>
