<script setup lang="ts">
import { computed } from 'vue'
import { X } from '@lucide/vue'

import { TooltipHint } from '@/components/ui/tooltip'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'
import PanelTabContent from './PanelTabContent.vue'

withDefaults(defineProps<{ inSheet?: boolean }>(), { inSheet: false })
const chat = useChatStore()
const panels = usePanelStore()

const tabs = computed(() => panels.tabsOf(chat.currentSessionId))
const active = computed(() => panels.activeTab(chat.currentSessionId))

function isActive(id: string): boolean {
  return active.value?.id === id
}

function selectTab(id: string): void {
  panels.selectTab(id)
}

function closeTab(id: string): void {
  panels.closeTab(chat.currentSessionId, id)
}

function closePanel(): void {
  panels.closeTabs(chat.currentSessionId)
}
</script>

<template>
  <aside
    v-if="active"
    class="flex h-full min-h-0 w-full flex-col bg-chat"
    :class="inSheet ? '' : 'border-l border-border'"
    aria-label="侧栏内容"
  >
    <header class="flex h-12 shrink-0 items-center gap-1 border-b border-border bg-chat pl-2 pr-1.5">
      <div class="flex min-w-0 flex-1 items-stretch gap-0.5 overflow-x-auto">
        <div
          v-for="tab in tabs"
          :key="tab.id"
          class="group/tab relative flex h-12 max-w-[190px] shrink-0 items-center"
        >
          <TooltipHint :text="tab.title">
            <button
              type="button"
              class="flex h-full min-w-0 items-center rounded-t-md px-2.5 text-[12px] transition-colors"
              :class="isActive(tab.id)
                ? 'text-foreground'
                : 'text-muted-foreground hover:bg-surface hover:text-foreground'"
              @click="selectTab(tab.id)"
            >
              <span class="truncate">{{ tab.title }}</span>
            </button>
          </TooltipHint>
          <TooltipHint :text="`关闭 ${tab.title}`">
            <button
              type="button"
              class="mr-0.5 grid size-5 shrink-0 place-items-center rounded text-muted-foreground/55 transition-colors hover:bg-surface-strong hover:text-foreground"
              :aria-label="`关闭：${tab.title}`"
              @click="closeTab(tab.id)"
            >
              <X class="size-3" />
            </button>
          </TooltipHint>
          <span
            v-if="isActive(tab.id)"
            class="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-brand"
          />
        </div>
      </div>

      <TooltipHint text="关闭侧栏">
        <button
          type="button"
          class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
          aria-label="关闭侧栏"
          @click="closePanel"
        >
          <X class="size-4" />
        </button>
      </TooltipHint>
    </header>

    <div class="min-h-0 flex-1 bg-surface/60 p-3">
      <PanelTabContent :tab="active" />
    </div>
  </aside>
</template>
