<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Archive, ArchiveRestore, Loader2, RefreshCw, Trash2 } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { TooltipHint } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/http'
import { formatRelativeTime, formatTokens } from '@/lib/format'
import { useChatStore } from '@/stores/chat'
import type { ChatSession } from '@/types/api'

const chat = useChatStore()
const loading = ref(!chat.sessionsLoaded)
const error = ref<string | null>(null)
const restoringId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

const sessions = computed(() => chat.archivedSessions)

async function refresh(): Promise<void> {
  loading.value = !chat.sessionsLoaded
  error.value = null
  try {
    await chat.refreshSessions()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function restore(session: ChatSession): Promise<void> {
  if (restoringId.value) return
  restoringId.value = session.id
  try {
    await chat.unarchiveSession(session)
    toast.success('已恢复到对话列表')
  } catch (caught) {
    toast.error('恢复失败', { description: errorMessage(caught) })
  } finally {
    restoringId.value = null
  }
}

async function remove(session: ChatSession): Promise<void> {
  if (deletingId.value !== session.id) {
    deletingId.value = session.id
    return
  }
  try {
    await chat.deleteSession(session)
    deletingId.value = null
    toast.success('对话已删除')
  } catch (caught) {
    toast.error('删除失败', { description: errorMessage(caught) })
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="space-y-3 pt-3">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">已归档对话</p>
      <Button variant="outline" class="h-9" :disabled="loading" @click="refresh">
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <div v-if="loading" class="overflow-hidden rounded-lg border border-border bg-card">
      <div v-for="index in 3" :key="index" class="space-y-2 border-t border-border px-4 py-4 first:border-t-0">
        <div class="h-3 w-40 animate-pulse rounded-full bg-muted" />
        <div class="h-3 w-24 animate-pulse rounded-full bg-muted" />
      </div>
    </div>

    <div
      v-else-if="error"
      class="flex flex-col items-center rounded-lg border border-border bg-card px-6 py-16 text-center"
    >
      <p class="text-sm font-medium">归档加载失败</p>
      <p class="mt-1.5 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ error }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="refresh">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <div
      v-else-if="!sessions.length"
      class="flex flex-col items-center rounded-lg border border-border bg-card px-6 py-16 text-center"
    >
      <span class="grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
        <Archive class="size-4" />
      </span>
      <p class="mt-4 text-sm font-medium">还没有归档的对话</p>
      <p class="mt-1.5 max-w-[320px] text-sm leading-6 text-muted-foreground">
        归档的对话会保留在这里，随时可以恢复到对话列表。
      </p>
    </div>

    <div v-else class="overflow-hidden rounded-lg border border-border bg-card">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="group flex items-center gap-3 border-t border-border px-4 py-3 transition-colors first:border-t-0 hover:bg-muted/40"
      >
        <span class="grid size-9 shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground">
          <Archive class="size-4" :stroke-width="1.7" />
        </span>
        <div class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium leading-5">
            {{ session.title || '未命名对话' }}
          </span>
          <span class="mt-0.5 block truncate text-xs leading-4 text-muted-foreground">
            最后活跃 {{ formatRelativeTime(session.last_run_at) }}
            <template v-if="session.usage.total_tokens">
              · {{ formatTokens(session.usage.total_tokens) }} tokens
            </template>
            <template v-if="session.usage.cache_read_tokens">
              · 缓存命中 {{ formatTokens(session.usage.cache_read_tokens) }}
            </template>
          </span>
        </div>

        <div class="flex shrink-0 items-center gap-1">
          <TooltipHint text="恢复对话">
            <Button
              variant="ghost"
              class="h-9 gap-1 px-2.5 text-sm text-muted-foreground"
              aria-label="恢复对话"
              :disabled="restoringId === session.id"
              @click="restore(session)"
            >
              <Loader2 v-if="restoringId === session.id" class="size-3.5 animate-spin" />
              <ArchiveRestore v-else class="size-3.5" />
              恢复
            </Button>
          </TooltipHint>
          <template v-if="deletingId === session.id">
            <Button variant="destructive" size="sm" @click="remove(session)">确认删除</Button>
            <Button variant="ghost" size="sm" class="text-muted-foreground" @click="deletingId = null">取消</Button>
          </template>
          <TooltipHint v-else text="删除对话">
            <Button
              variant="ghost"
              size="icon-sm"
              class="text-muted-foreground hover:text-destructive"
              aria-label="删除对话"
              @click="remove(session)"
            >
              <Trash2 class="size-4" />
            </Button>
          </TooltipHint>
        </div>
      </div>
    </div>

    <Button
      v-if="chat.archivedHasMore"
      variant="outline"
      class="h-9 w-full text-sm"
      :disabled="chat.loadingMoreArchived"
      @click="chat.loadMoreArchivedSessions()"
    >
      {{ chat.loadingMoreArchived ? '加载中…' : '加载更多归档' }}
    </Button>
  </div>
</template>
