<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { PanelLeft, Pencil, Share2 } from '@lucide/vue'

import { errorMessage } from '@/lib/http'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import ShareDialog from './ShareDialog.vue'

const chat = useChatStore()
const ui = useUiStore()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const editing = ref(false)
const titleDraft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)
const sharing = ref(false)

const session = computed(() => chat.currentSession)
const title = computed(() => session.value?.title || '新对话')

function toggleSidebar(): void {
  if (isDesktop.value) ui.toggleSidebar()
  else ui.openMobileSidebar()
}

async function startEditing(): Promise<void> {
  if (!session.value) return
  titleDraft.value = title.value
  editing.value = true
  await nextTick()
  titleInput.value?.focus()
  titleInput.value?.select()
}

function cancelEditing(): void {
  editing.value = false
}

async function saveTitle(): Promise<void> {
  if (!editing.value || !session.value) return
  editing.value = false
  const next = titleDraft.value.trim()
  if (!next || next === title.value) return
  try {
    await chat.renameSession(session.value, next)
  } catch (error) {
    toast.error('重命名失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-1.5 border-b border-border/70 px-2.5 sm:px-4">
    <button
      type="button"
      class="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
      aria-label="切换侧边栏"
      @click="toggleSidebar"
    >
      <PanelLeft class="size-[17px]" :stroke-width="1.8" />
    </button>

    <div class="min-w-0 flex-1 pl-0.5">
      <input
        v-if="editing"
        ref="titleInput"
        v-model="titleDraft"
        class="h-8 w-full max-w-[420px] rounded-md border border-input bg-background px-2 text-[14px] font-medium outline-none focus:border-foreground/25"
        maxlength="200"
        @blur="saveTitle"
        @keydown.enter.prevent="saveTitle"
        @keydown.esc="cancelEditing"
      >
      <button
        v-else
        type="button"
        class="group/title flex min-w-0 max-w-full items-center gap-1.5 rounded-md px-1 py-1 text-left"
        :class="session ? 'cursor-text' : 'cursor-default'"
        :aria-label="session ? `重命名对话：${title}` : undefined"
        @click="session && startEditing()"
      >
        <span class="truncate text-[14px] font-medium tracking-[-0.01em]">{{ title }}</span>
        <Pencil
          v-if="session"
          class="size-3 shrink-0 text-muted-foreground/0 transition-colors group-hover/title:text-muted-foreground/70"
        />
      </button>
    </div>

    <button
      v-if="session"
      type="button"
      class="grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
      aria-label="分享这段对话"
      @click="sharing = true"
    >
      <Share2 class="size-[17px]" :stroke-width="1.8" />
    </button>

    <ShareDialog v-if="session" v-model:open="sharing" :session-id="session.id" />
  </header>
</template>
