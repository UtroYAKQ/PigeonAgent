<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, Loader2, Lock } from '@lucide/vue'

import { sharesApi } from '@/api/shares'
import BrandMark from '@/components/brand/BrandMark.vue'
import ArtifactBlock from '@/components/chat/ArtifactBlock.vue'
import MarkdownMessage from '@/components/chat/MarkdownMessage.vue'
import SourcesRow from '@/components/chat/SourcesRow.vue'
import ThinkingChain from '@/components/chat/ThinkingChain.vue'
import TurnFiles from '@/components/chat/TurnFiles.vue'
import { errorMessage } from '@/lib/http'
import { formatDateTime } from '@/lib/format'
import { buildTurnView, hasAssistantOutput } from '@/lib/turnModel'
import { useUiStore } from '@/stores/ui'
import type { SessionRun, SharedConversation } from '@/types/api'

const route = useRoute()
const ui = useUiStore()

const token = computed(() => String(route.params.token ?? ''))
const conversation = ref<SharedConversation | null>(null)
const runs = ref<SessionRun[]>([])
const hasMore = ref(false)
const loading = ref(true)
const loadingEarlier = ref(false)
const failure = ref<string | null>(null)

// 只读渲染：每个 run 单独算一份 turn 视图，不碰工作区的 chat store
const turns = computed(() =>
  runs.value.map(run => ({ run, view: buildTurnView(run, null) })),
)

const siteName = 'PigeonAgent'

let robots: HTMLMetaElement | null = null

function setRobots(): void {
  // 分享页不该被搜索引擎收走：链接本身就是访问凭证
  robots = document.createElement('meta')
  robots.name = 'robots'
  robots.content = 'noindex, nofollow'
  document.head.appendChild(robots)
}

function clearRobots(): void {
  robots?.remove()
  robots = null
  document.title = siteName
}

async function load(): Promise<void> {
  loading.value = true
  failure.value = null
  try {
    const result = await sharesApi.read(token.value)
    conversation.value = result
    runs.value = result.runs
    hasMore.value = result.has_more
    document.title = `${result.session.title || '分享的对话'} · ${siteName}`
  } catch (caught) {
    failure.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function loadEarlier(): Promise<void> {
  const oldest = runs.value[0]
  if (!oldest || loadingEarlier.value) return
  loadingEarlier.value = true
  try {
    const older = await sharesApi.read(token.value, oldest.id)
    runs.value = [...older.runs, ...runs.value]
    hasMore.value = older.has_more
  } catch (caught) {
    failure.value = errorMessage(caught)
  } finally {
    loadingEarlier.value = false
  }
}

onMounted(() => {
  setRobots()
  void load()
})

onBeforeUnmount(clearRobots)
</script>

<template>
  <div class="min-h-dvh bg-chat text-foreground">
    <header class="sticky top-0 z-10 border-b border-border/70 bg-background/85 backdrop-blur">
      <div class="mx-auto flex h-14 w-full max-w-chat items-center gap-2.5 px-4 sm:px-6">
        <BrandMark size="sm" />
        <span class="min-w-0 flex-1 truncate text-[14px] font-medium tracking-[-0.01em]">
          {{ conversation?.session.title || '分享的对话' }}
        </span>
        <span
          class="hidden shrink-0 items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground min-[430px]:inline-flex"
        >
          <Lock class="size-3" :stroke-width="1.8" />
          只读分享
        </span>
      </div>
    </header>

    <main class="mx-auto w-full max-w-chat px-4 pb-16 pt-6 sm:px-6 sm:pt-8">
      <div v-if="loading" class="min-h-[160px]">
        <div class="animate-pulse space-y-8">
          <div class="ml-auto h-16 w-2/3 rounded-xl bg-surface" />
          <div class="space-y-3">
            <div class="h-3 w-32 rounded-full bg-surface" />
            <div class="h-3 w-full rounded-full bg-surface" />
            <div class="h-3 w-5/6 rounded-full bg-surface" />
          </div>
        </div>
      </div>

      <div v-else-if="failure && !runs.length" class="flex flex-col items-center py-16 text-center">
        <span class="grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
          <AlertTriangle class="size-4" />
        </span>
        <p class="mt-4 text-[14px] font-medium">打不开这段对话</p>
        <p class="mt-1.5 max-w-[320px] text-[12.5px] leading-5 text-muted-foreground">
          {{ failure }}
        </p>
        <button
          type="button"
          class="mt-5 inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-[12.5px] transition-colors hover:bg-surface"
          @click="load"
        >
          <Loader2 v-if="loading" class="size-3.5 animate-spin" />
          重试
        </button>
      </div>

      <template v-else>
        <p v-if="failure" class="mb-6 rounded-lg border border-destructive/20 px-3 py-2 text-[12.5px] text-destructive">
          {{ failure }}
        </p>

        <div v-if="hasMore" class="mb-8 flex justify-center">
          <button
            type="button"
            class="inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-[12px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground disabled:opacity-50"
            :disabled="loadingEarlier"
            @click="loadEarlier"
          >
            <Loader2 v-if="loadingEarlier" class="size-3 animate-spin" />
            加载更早的消息
          </button>
        </div>

        <div class="flex flex-col gap-10">
          <article v-for="turn in turns" :key="turn.run.id" class="flex flex-col gap-4">
            <div v-if="turn.view.userText" class="ml-auto max-w-[85%]">
              <div class="rounded-2xl bg-surface px-4 py-3 text-[14px] leading-7 whitespace-pre-wrap break-words">
                {{ turn.view.userText }}
              </div>
            </div>

            <div class="min-w-0">
              <template v-for="(segment, index) in turn.view.segments" :key="segment.id">
                <ThinkingChain
                  v-if="segment.kind === 'chain'"
                  :chain="segment.entries"
                  :plan="index === turn.view.segments.length - 1 ? turn.view.plan : null"
                  :is-streaming="false"
                  :status="turn.view.status"
                  :default-open="ui.autoExpandThinking"
                  :default-details-open="ui.autoExpandToolDetails"
                />
                <ArtifactBlock
                  v-else-if="segment.kind === 'artifact'"
                  :media="segment.media"
                  :credits="segment.credits"
                />
                <MarkdownMessage v-else :content="segment.text" />
              </template>

              <TurnFiles v-if="turn.view.attachments.length" :media="turn.view.attachments" />

              <SourcesRow v-if="turn.view.sources.length" :sources="turn.view.sources" />

              <div
                v-if="turn.view.error || (!hasAssistantOutput(turn.view) && turn.view.userText)"
                class="mt-3 flex items-start gap-2 text-[12px] leading-5 text-muted-foreground"
              >
                <AlertTriangle class="mt-0.5 size-3.5 shrink-0" />
                <span class="min-w-0 flex-1">
                  {{ turn.view.error?.message || '这一轮没有可展示的内容。' }}
                </span>
              </div>
            </div>
          </article>
        </div>

        <footer class="mt-14 border-t border-border pt-5 text-[12px] leading-6 text-muted-foreground">
          <p v-if="conversation">
            这段对话由作者以只读方式分享，{{ formatDateTime(conversation.expires_at) }} 后链接失效。
          </p>
          <p class="mt-1">
            图片与产出文件需要登录原作者账号才能查看，这里只保留文字与过程记录。
            <RouterLink to="/" class="underline underline-offset-4 hover:text-foreground">
              在 {{ siteName }} 里继续对话
            </RouterLink>
          </p>
        </footer>
      </template>
    </main>
  </div>
</template>
