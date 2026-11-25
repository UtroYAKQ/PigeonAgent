<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowLeft, Loader2, Radio, RefreshCw } from '@lucide/vue'

import { adminApi } from '@/api/admin'
import ReadOnlyTurn from '@/components/chat/ReadOnlyTurn.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/http'
import { formatAdminTime } from '@/lib/admin'
import { formatTokens } from '@/lib/format'
import { applyAgUiEvent } from '@/lib/agui'
import { StreamGoneError, streamRun } from '@/lib/sse'
import {
  buildTurnView,
  mergeTurnViews,
  projectLiveRun,
  type TurnView,
} from '@/lib/turnModel'
import { runHasResumeMarker } from '@/stores/chat/shared'
import type { AdminSession, LiveRun, SessionRun } from '@/types/api'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ back: [] }>()

const PAGE_SIZE = 200
const RETRY_DELAY_MS = 650

const session = ref<AdminSession | null>(null)
const runs = ref<SessionRun[]>([])
const hasMore = ref(false)
const loading = ref(true)
const loadingEarlier = ref(false)
const failure = ref<string | null>(null)
const streamNote = ref<string | null>(null)
const live = ref<LiveRun | null>(null)

let abortController: AbortController | null = null
let streamGeneration = 0
let loadGeneration = 0
let disposed = false

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

const historyTurns = computed(() =>
  runs.value
    .filter(run => run.id !== live.value?.runId)
    .map(run => ({ run, view: buildTurnView(run, null) })),
)

const liveTurn = computed<{ run: SessionRun; view: TurnView } | null>(() => {
  const current = live.value
  if (!current) return null
  const active = runs.value.find(run => run.id === current.runId)
    ?? projectLiveRun(runs.value, current)
  if (!active) return null
  const liveView = buildTurnView(active, current)
  if (!runs.value.some(run => run.id === current.runId) || !runHasResumeMarker(active)) {
    return { run: active, view: liveView }
  }
  // 同一 run 续写时事件流只有续写段：先铺上已落库的前半段，再接实时段
  const combined = mergeTurnViews(buildTurnView(active, null), liveView)
  combined.userText = liveView.userText
  combined.userImages = liveView.userImages
  combined.userVideos = liveView.userVideos
  combined.userResources = liveView.userResources
  return { run: active, view: combined }
})

const liveStreaming = computed(() => Boolean(live.value && !live.value.finished))

function stopLive(): void {
  streamGeneration += 1
  abortController?.abort()
  abortController = null
  live.value = null
}

function startLive(runId: string): void {
  stopLive()
  streamGeneration += 1
  const generation = streamGeneration
  // 续写段的工具结果一般没有对应的 START；用已落库的调用名补上
  const toolNames = new Map<string, string>()
  for (const item of runs.value.find(run => run.id === runId)?.content ?? []) {
    if (item.type === 'tool_call') toolNames.set(item.tool_call_id, item.tool_name)
  }
  live.value = {
    runId,
    sessionId: props.sessionId,
    blocks: [],
    usage: null,
    compaction: null,
    error: null,
    errorCode: null,
    connected: false,
    finished: false,
  }
  void attach(runId, generation, toolNames)
}

async function attach(
  runId: string,
  generation: number,
  toolNames: Map<string, string>,
): Promise<void> {
  let sequence = 0
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (disposed || generation !== streamGeneration) return
    const controller = new AbortController()
    abortController = controller
    try {
      await streamRun({
        url: adminApi.sessionEventsUrl(props.sessionId, runId, sequence),
        signal: controller.signal,
        onSequence: value => {
          sequence = value
        },
        onOpen: () => {
          if (generation === streamGeneration && live.value) live.value.connected = true
        },
        onEvent: event => {
          if (generation !== streamGeneration) return
          if (live.value) {
            applyAgUiEvent(live.value, event, id => toolNames.get(id))
          }
        },
      })
      break
    } catch (error) {
      if (controller.signal.aborted || generation !== streamGeneration) return
      if (error instanceof StreamGoneError) break
      if (attempt >= 2) {
        streamNote.value = errorMessage(error)
        break
      }
      await sleep(RETRY_DELAY_MS)
    }
  }
  if (disposed || generation !== streamGeneration) return
  await settle(runId, generation)
}

/** 流结束后等后端把 run 状态和内容落完，再切回历史视图。 */
async function settle(runId: string, generation: number): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await sleep(attempt === 0 ? 250 : Math.min(1_000 * 2 ** (attempt - 1), 5_000))
    if (disposed || generation !== streamGeneration) return
    try {
      const [detail, list] = await Promise.all([
        adminApi.session(props.sessionId),
        adminApi.sessionRuns(props.sessionId, { limit: PAGE_SIZE }),
      ])
      if (disposed || generation !== streamGeneration) return
      session.value = detail
      runs.value = list.items
      hasMore.value = Boolean(list.has_more)
      if (!detail.live || detail.active_run_id !== runId) {
        live.value = null
        return
      }
    } catch {
      // 状态还没落完就再等一轮
    }
  }
  if (disposed || generation !== streamGeneration) return
  live.value = null
  streamNote.value = '实时流已结束，但没等到最终状态；刷新可查看最新内容。'
}

async function load(): Promise<void> {
  const generation = ++loadGeneration
  loading.value = true
  failure.value = null
  streamNote.value = null
  stopLive()
  try {
    const [detail, list] = await Promise.all([
      adminApi.session(props.sessionId),
      adminApi.sessionRuns(props.sessionId, { limit: PAGE_SIZE }),
    ])
    if (disposed || generation !== loadGeneration) return
    session.value = detail
    runs.value = list.items
    hasMore.value = Boolean(list.has_more)
    if (detail.live && detail.active_run_id) startLive(detail.active_run_id)
  } catch (caught) {
    if (!disposed && generation === loadGeneration) failure.value = errorMessage(caught)
  } finally {
    if (!disposed && generation === loadGeneration) loading.value = false
  }
}

async function loadEarlier(): Promise<void> {
  const oldest = runs.value[0]
  if (!oldest || loadingEarlier.value) return
  loadingEarlier.value = true
  try {
    const older = await adminApi.sessionRuns(props.sessionId, {
      before_run_id: oldest.id,
      limit: PAGE_SIZE,
    })
    if (disposed) return
    runs.value = [...older.items, ...runs.value]
    hasMore.value = Boolean(older.has_more)
  } catch (caught) {
    streamNote.value = errorMessage(caught)
  } finally {
    loadingEarlier.value = false
  }
}

onMounted(() => {
  void load()
})

onBeforeUnmount(() => {
  disposed = true
  stopLive()
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start gap-3">
      <Button variant="ghost" class="h-8 -ml-2 text-muted-foreground" @click="emit('back')">
        <ArrowLeft class="size-4" />
        会话列表
      </Button>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="max-w-[420px] truncate text-sm font-medium">
            {{ session?.title || '未命名会话' }}
          </h2>
          <Badge v-if="liveStreaming" variant="outline" class="gap-1.5">
            <Radio class="size-3 animate-pulse" />
            实时订阅中
          </Badge>
          <Badge v-else-if="session?.live" variant="outline">运行中</Badge>
          <Badge v-if="session" :variant="session.status === 'active' ? 'secondary' : 'outline'">
            {{ session.status === 'active' ? '活跃' : '已归档' }}
          </Badge>
        </div>
        <p class="mt-1 truncate font-mono text-[11px] text-muted-foreground">{{ props.sessionId }}</p>
        <p v-if="session" class="mt-1 truncate text-xs text-muted-foreground">
          {{ session.owner_display_name || session.owner_email || '未知用户' }}
          <span v-if="session.owner_email && session.owner_display_name"> · {{ session.owner_email }}</span>
          <span> · {{ session.run_count }} 轮 · {{ formatTokens(session.usage.total_tokens) }} tokens</span>
          <span> · 最后活跃 {{ formatAdminTime(session.last_run_at) }}</span>
        </p>
      </div>
      <Button variant="outline" class="h-8" :disabled="loading" @click="load">
        <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <div v-if="loading" class="animate-pulse space-y-8 py-6">
      <div class="ml-auto h-12 w-2/3 rounded-xl bg-surface" />
      <div class="space-y-3">
        <div class="h-3 w-32 rounded-full bg-surface" />
        <div class="h-3 w-full rounded-full bg-surface" />
        <div class="h-3 w-5/6 rounded-full bg-surface" />
      </div>
    </div>

    <div v-else-if="failure && !runs.length" class="flex flex-col items-center py-14 text-center">
      <span class="grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
        <AlertTriangle class="size-4" />
      </span>
      <p class="mt-4 text-sm font-medium">会话加载失败</p>
      <p class="mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ failure }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <template v-else>
      <p v-if="failure" class="rounded-lg border border-destructive/20 px-3 py-2 text-[12.5px] text-destructive">
        {{ failure }}
      </p>
      <p v-if="streamNote" class="rounded-lg border border-border px-3 py-2 text-[12.5px] text-muted-foreground">
        {{ streamNote }}
      </p>

      <div v-if="hasMore" class="flex justify-center">
        <Button variant="outline" class="h-8 text-muted-foreground" :disabled="loadingEarlier" @click="loadEarlier">
          <Loader2 v-if="loadingEarlier" class="size-3.5 animate-spin" />
          加载更早的消息
        </Button>
      </div>

      <div v-if="historyTurns.length || liveTurn" class="flex flex-col gap-10 py-2">
        <ReadOnlyTurn v-for="turn in historyTurns" :key="turn.run.id" :view="turn.view" />
        <ReadOnlyTurn
          v-if="liveTurn"
          :key="liveTurn.run.id"
          :view="liveTurn.view"
          :streaming="liveStreaming"
        />
      </div>
      <div v-else class="py-14 text-center text-sm text-muted-foreground">这个会话还没有消息。</div>

      <p class="border-t border-border pt-4 text-[12px] leading-5 text-muted-foreground">
        后台只读查看。图片与文件需要原作者登录后才能加载；运行中的会话会自动订阅实时事件。
      </p>
    </template>
  </div>
</template>