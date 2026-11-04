<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLocalStorage, useMediaQuery, useWindowSize } from '@vueuse/core'
import { useRoute } from 'vue-router'
import { toast } from 'vue-sonner'
import { AlertTriangle, ArrowDown, Loader2, RefreshCw } from '@lucide/vue'

import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { TooltipHint } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/http'
import { onScrollIntent } from '@/lib/scrollIntent'
import { buildTurnView, projectLiveRun } from '@/lib/turnModel'
import { groupTurnRuns } from '@/lib/turns'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'
import { useUiStore } from '@/stores/ui'
import { useChatScroll } from '@/composables/useChatScroll'
import { useComposerFlight } from '@/composables/useComposerFlight'
import AppSidebar from '@/components/chat/AppSidebar.vue'
import AssistantTurn from '@/components/chat/AssistantTurn.vue'
import ChatHeader from '@/components/chat/ChatHeader.vue'
import Composer from '@/components/chat/Composer.vue'
import ContextCheckpoint from '@/components/chat/ContextCheckpoint.vue'
import ConversationTurn from '@/components/chat/ConversationTurn.vue'
import EmptyState from '@/components/chat/EmptyState.vue'
import FlightField from '@/components/brand/FlightField.vue'
import PreviewPanel from '@/components/chat/PreviewPanel.vue'

const chat = useChatStore()
const panels = usePanelStore()
const ui = useUiStore()
const route = useRoute()
const isWide = useMediaQuery('(min-width: 1280px)')
const { width: windowWidth } = useWindowSize()
const previewWidth = useLocalStorage('pigeon.preview-width', 440)
const resizingPreview = ref(false)
let previewStartX = 0
let previewStartWidth = 0

const composerInnerEl = ref<HTMLElement | null>(null)
const { landing: composerLanding, begin: beginFlight, cancel: cancelFlight } =
  useComposerFlight(composerInnerEl)

const scrollEl = ref<HTMLElement | null>(null)
const contentEl = ref<HTMLElement | null>(null)
const { atBottom, showButton, scrollToBottom, forceScroll } = useChatScroll(scrollEl, contentEl)

const showEmpty = computed(() => {
  if (!chat.currentSessionId) return true
  if (chat.loadingSession || chat.sessionError) return false
  if (chat.currentSession?.status === 'archived') return false
  return !chat.hasMessages
})

const turnGroups = computed(() => groupTurnRuns(chat.runs))
const lastRunId = computed(() => turnGroups.value[turnGroups.value.length - 1]?.id ?? null)
const previewMaxWidth = computed(() => Math.max(360, Math.min(760, windowWidth.value - 824)))
const effectivePreviewWidth = computed(() =>
  Math.min(Math.max(previewWidth.value, 320), previewMaxWidth.value),
)

const liveOnlyRun = computed(() => projectLiveRun(chat.runs, chat.liveRun))

const liveOnlyView = computed(() => {
  const run = liveOnlyRun.value
  return run ? buildTurnView(run, chat.liveRun) : null
})

const liveOnlyCompaction = computed(() => (liveOnlyRun.value ? chat.liveRun?.compaction ?? null : null))

const noModels = computed(() => chat.modelsLoaded && !chat.activeModels.length)
const loadFailed = computed(() => Boolean(chat.bootstrapError) && !chat.modelsLoaded)
const isArchived = computed(() => chat.currentSession?.status === 'archived')
const composerAvailable = computed(
  () => showEmpty.value || (Boolean(chat.currentSession) && !chat.sessionError),
)
const activePanelTab = computed(() => panels.activeTab(chat.currentSessionId))
const previewSheetOpen = ref(false)
let sessionsTimer: number | null = null

watch(activePanelTab, (tab) => {
  if (tab && !isWide.value) previewSheetOpen.value = true
  if (!tab) previewSheetOpen.value = false
})

watch(isWide, (wide) => {
  if (!activePanelTab.value) return
  // 全页只留一个活着的 iframe：宽屏用内联列，窄屏用抽屉，跨断点时把另一边关掉
  previewSheetOpen.value = !wide
})

function onPreviewSheet(open: boolean): void {
  previewSheetOpen.value = open
  if (!open) panels.closeTabs(chat.currentSessionId)
}

function startPreviewResize(event: PointerEvent): void {
  const target = event.currentTarget as HTMLElement | null
  if (!target) return
  previewStartX = event.clientX
  previewStartWidth = effectivePreviewWidth.value
  resizingPreview.value = true
  target.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function movePreviewResize(event: PointerEvent): void {
  if (!resizingPreview.value) return
  const next = previewStartWidth + (previewStartX - event.clientX)
  previewWidth.value = Math.min(Math.max(next, 320), previewMaxWidth.value)
}

function stopPreviewResize(event: PointerEvent): void {
  if (!resizingPreview.value) return
  resizingPreview.value = false
  const target = event.currentTarget as HTMLElement | null
  if (target?.hasPointerCapture(event.pointerId)) {
    target.releasePointerCapture(event.pointerId)
  }
}

watch(
  showEmpty,
  (empty, wasEmpty) => {
    if (!wasEmpty || empty || chat.loadingSession || chat.sessionError) return
    const firstRect = composerInnerEl.value?.getBoundingClientRect()
    if (!firstRect || firstRect.width <= 0) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    beginFlight(firstRect)
  },
  { flush: 'pre' },
)

onMounted(async () => {
  // 先把定时器建起来：bootstrap 期间卸载时 onBeforeUnmount 才有东西可清
  sessionsTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    if (chat.busy || chat.loadingSession || !chat.sessionsLoaded) return
    void chat.refreshSessions().catch(() => undefined)
  }, 20_000)
  try {
    await chat.bootstrap()
  } catch (error) {
    toast.error('加载工作区失败', { description: errorMessage(error) })
  }
})

onBeforeUnmount(() => {
  if (sessionsTimer !== null) window.clearInterval(sessionsTimer)
  cancelFlight()
})

watch(
  () => route.params.id as string | undefined,
  async (id) => {
    if (!id) {
      chat.resetCurrent()
      return
    }
    try {
      await chat.openSession(id)
    } catch {
      // 错误详情由页面内的错误状态呈现
    }
  },
  { immediate: true },
)

onMounted(
  () =>
    onScrollIntent(async (smooth) => {
      await nextTick()
      if (smooth && !atBottom.value) {
        scrollToBottom()
        return
      }
      void forceScroll()
    }),
)

async function loadEarlier(): Promise<void> {
  const element = scrollEl.value
  if (!element) return
  const previousHeight = element.scrollHeight
  const previousTop = element.scrollTop
  try {
    await chat.loadEarlierRuns()
    await nextTick()
    element.scrollTop = element.scrollHeight - previousHeight + previousTop
  } catch (error) {
    toast.error('加载历史消息失败', { description: errorMessage(error) })
  }
}

/** 统一的"再试一次"：标题按场景给，真实原因进 toast 描述。 */
function retry(task: () => Promise<unknown>, failure: string): Promise<void> {
  return task()
    .then(() => undefined)
    .catch(error => {
      toast.error(failure, { description: errorMessage(error) })
    })
}

function retrySession(): Promise<void> {
  const sessionId = chat.currentSessionId
  if (!sessionId) return Promise.resolve()
  return retry(() => chat.openSession(sessionId), '加载对话失败')
}

function retryModels(): Promise<void> {
  return retry(() => chat.refreshModels(), '加载模型失败')
}

function retryBootstrap(): Promise<void> {
  return retry(() => chat.bootstrap(), '仍然无法连接服务')
}

async function restoreSession(): Promise<void> {
  if (!chat.currentSession) return
  try {
    await chat.unarchiveSession(chat.currentSession)
    toast.success('已恢复到对话列表')
  } catch (error) {
    toast.error('恢复失败', { description: errorMessage(error) })
  }
}
</script>

<template>
  <div class="flex h-dvh w-full overflow-hidden bg-chat">
    <aside
      class="hidden h-full shrink-0 overflow-hidden border-r border-sidebar-border transition-[width] duration-200 ease-out lg:block"
      :class="ui.sidebarCollapsed ? 'w-0 border-r-0' : 'w-64'"
    >
      <div
        class="h-full w-64 transition-opacity duration-200"
        :class="ui.sidebarCollapsed ? 'opacity-0' : 'opacity-100'"
      >
        <AppSidebar />
      </div>
    </aside>

    <div class="flex min-h-0 min-w-0 flex-1">
      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <ChatHeader />

      <template v-if="!showEmpty">
        <div
          v-if="chat.sessionError"
          class="flex min-h-0 flex-1 items-center justify-center px-4 py-10"
        >
          <div class="flex w-full max-w-[340px] flex-col items-center text-center">
            <span class="grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
              <AlertTriangle class="size-4" />
            </span>
            <p class="mt-4 text-[14px] font-medium">无法打开这条对话</p>
            <p class="mt-1.5 max-w-[320px] text-[12.5px] leading-5 text-muted-foreground">
              {{ chat.sessionError }}
            </p>
            <button
              type="button"
              class="mt-5 inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-[12.5px] transition-colors hover:bg-surface"
              @click="retrySession"
            >
              <RefreshCw class="size-3.5" />
              重试
            </button>
          </div>
        </div>

        <div v-else class="relative min-h-0 flex-1">
          <div ref="scrollEl" class="h-full overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
            <div
              ref="contentEl"
              class="mx-auto w-full max-w-chat px-4 pb-10 pt-6 sm:px-6 sm:pt-8"
            >
              <div v-if="chat.loadingSession" class="min-h-[160px]">
                <div class="animate-pulse space-y-8">
                  <div class="ml-auto h-20 w-2/3 rounded-xl bg-surface" />
                  <div class="space-y-3">
                    <div class="h-3 w-32 rounded-full bg-surface" />
                    <div class="h-3 w-full rounded-full bg-surface" />
                    <div class="h-3 w-5/6 rounded-full bg-surface" />
                    <div class="h-3 w-3/4 rounded-full bg-surface" />
                  </div>
                </div>
              </div>

              <template v-else>
                <div v-if="chat.runsHasMore" class="mb-8 flex justify-center">
                  <button
                    type="button"
                    class="inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-[12px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground disabled:opacity-50"
                    :disabled="chat.loadingEarlier"
                    @click="loadEarlier"
                  >
                    <Loader2 v-if="chat.loadingEarlier" class="size-3 animate-spin" />
                    加载更早的消息
                  </button>
                </div>

                <div
                  :key="chat.currentSessionId ?? 'empty'"
                  class="session-content flex flex-col gap-10 transition-transform duration-500 ease-out"
                  :class="composerLanding ? 'translate-y-2' : ''"
                >
                  <ConversationTurn
                    v-for="group in turnGroups"
                    :key="group.id"
                    :group="group"
                    :is-last="group.id === lastRunId && !liveOnlyRun"
                  />
                  <template v-if="liveOnlyRun && liveOnlyView">
                    <ContextCheckpoint
                      v-if="liveOnlyCompaction"
                      :state="liveOnlyCompaction.status"
                      :summary="liveOnlyCompaction.summary"
                      :tokens-before="liveOnlyCompaction.tokensBefore"
                    />
                    <AssistantTurn
                      :run="liveOnlyRun"
                      :view="liveOnlyView"
                      :is-last="true"
                    />
                  </template>
                </div>
              </template>
            </div>
          </div>

          <button
            v-if="showButton"
            type="button"
            class="absolute bottom-4 left-1/2 grid size-8 -translate-x-1/2 place-items-center rounded-full border border-border bg-background text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            aria-label="滚动到最新消息"
            @click="scrollToBottom()"
          >
            <ArrowDown class="size-4" />
          </button>
        </div>
      </template>

      <div
        v-if="composerAvailable"
        class="relative flex min-h-0 flex-col"
          :class="showEmpty
            ? 'flex-1 overflow-y-auto [scrollbar-gutter:stable] px-4 py-10 sm:px-6 sm:py-14'
            : 'shrink-0 px-4 pb-3 sm:px-6'"
          :style="showEmpty ? undefined : { paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }"
        >
          <FlightField v-if="showEmpty" />
          <div
            ref="composerInnerEl"
            class="relative z-10 mx-auto w-full"
            :class="showEmpty ? 'my-auto max-w-chat-hero' : 'max-w-chat'"
          >
            <EmptyState v-if="showEmpty" />

            <div
              v-if="noModels || loadFailed"
              class="mb-2 flex items-center gap-2 rounded-xl border border-border bg-surface px-3.5 py-2.5 text-[12px] text-muted-foreground"
            >
              <span class="min-w-0 flex-1">{{ loadFailed ? '服务连接异常，暂时无法加载模型。' : '当前没有可用模型，暂时无法继续对话。' }}</span>
              <button
                type="button"
                class="inline-flex items-center gap-1 font-medium text-foreground hover:underline"
                @click="loadFailed ? retryBootstrap() : retryModels()"
              >
                <RefreshCw class="size-3" />
                重新检查
              </button>
            </div>
            <div
              v-if="!showEmpty && isArchived"
              class="flex items-center gap-3 rounded-[22px] border border-border bg-surface px-4 py-3.5"
            >
              <span class="min-w-0 flex-1 text-[12.5px] leading-5 text-muted-foreground">
                这条对话已归档。恢复后可以继续发送消息。
              </span>
              <button
                type="button"
                class="h-8 shrink-0 rounded-full border border-border bg-background px-3 text-[12px] font-medium transition-colors hover:bg-surface-strong"
                @click="restoreSession"
              >
                恢复对话
              </button>
            </div>
            <Composer
              v-else
              :hero="showEmpty"
              :show-disclaimer="!showEmpty"
            />
          </div>
        </div>
      </div>

      <Transition name="preview-panel">
        <div
          v-if="activePanelTab && isWide"
          class="relative h-full shrink-0 overflow-hidden"
          :style="{ width: `${effectivePreviewWidth}px` }"
        >
          <TooltipHint text="拖动调整预览宽度">
            <button
              type="button"
              class="group/splitter absolute inset-y-0 left-0 z-20 w-3 -translate-x-1/2 cursor-col-resize touch-none outline-none"
              aria-label="拖动调整预览宽度"
              @pointerdown="startPreviewResize"
              @pointermove="movePreviewResize"
              @pointerup="stopPreviewResize"
              @pointercancel="stopPreviewResize"
            >
              <span
                class="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-all duration-200 ease-out"
                :class="resizingPreview
                  ? 'h-11 w-1 bg-brand'
                  : 'h-9 w-[3px] bg-border group-hover/splitter:h-11 group-hover/splitter:w-1 group-hover/splitter:bg-foreground/30'"
              />
            </button>
          </TooltipHint>
          <PreviewPanel class="h-full w-full" />
        </div>
      </Transition>
    </div>

    <Sheet v-model:open="ui.mobileSidebarOpen">
      <SheetContent side="left" :show-close-button="false" class="w-[284px] max-w-[86vw] border-r border-sidebar-border bg-sidebar p-0">
        <SheetTitle class="sr-only">对话列表</SheetTitle>
        <SheetDescription class="sr-only">会话、分组与账户操作</SheetDescription>
        <AppSidebar mobile @navigate="ui.closeMobileSidebar()" />
      </SheetContent>
    </Sheet>

    <Sheet :open="previewSheetOpen" @update:open="onPreviewSheet">
      <SheetContent side="right" :show-close-button="false" class="w-full max-w-[min(94vw,560px)] border-l border-border bg-chat p-0">
        <SheetTitle class="sr-only">HTML 预览</SheetTitle>
        <SheetDescription class="sr-only">模型生成的 HTML 页面预览</SheetDescription>
        <PreviewPanel in-sheet />
      </SheetContent>
    </Sheet>
  </div>
</template>
