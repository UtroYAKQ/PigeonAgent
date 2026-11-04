<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Download, Image as ImageIcon, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { filesApi } from '@/api/files'
import type { ArtifactMedia } from '@/lib/turnModel'
import AuthMedia from './AuthMedia.vue'
import FileAttachment from './FileAttachment.vue'

const props = withDefaults(
  defineProps<{
    media: ArtifactMedia[]
    credits?: number | null
  }>(),
  { credits: null },
)

const visuals = computed(() => props.media.filter(item => item.kind !== 'file'))
const attachments = computed(() => props.media.filter(item => item.kind === 'file'))
const activeIndex = ref<number | null>(null)
const active = computed(() =>
  activeIndex.value === null ? null : visuals.value[activeIndex.value] ?? null,
)

function open(index: number): void {
  activeIndex.value = index
}

function close(): void {
  activeIndex.value = null
}

function step(delta: number): void {
  if (activeIndex.value === null || visuals.value.length < 2) return
  const total = visuals.value.length
  activeIndex.value = (activeIndex.value + delta + total) % total
}

async function download(item: ArtifactMedia): Promise<void> {
  try {
    const blob = item.fileId
      ? await filesApi.content(item.fileId)
      : item.data
        ? await (await fetch(`data:${item.mediaType};base64,${item.data}`)).blob()
        : null
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = item.name ?? `image.${item.mediaType.split('/')[1] ?? 'png'}`
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    revokeTimer = window.setTimeout(() => {
      URL.revokeObjectURL(url)
      revokeTimer = null
    }, 1000)
  } catch (error) {
    // 用户看到的是可重试的提示，真实原因留在控制台，不然下载挂了无从排查
    console.warn(`下载失败：${item.name ?? item.fileId ?? '未知文件'}`, error)
    toast.error('下载失败，请重试')
  }
}

function onKey(event: KeyboardEvent): void {
  if (activeIndex.value === null) return
  if (event.key === 'Escape') close()
  else if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
}

watch(activeIndex, (value) => {
  if (value === null) window.removeEventListener('keydown', onKey)
  else window.addEventListener('keydown', onKey)
})

let revokeTimer: number | null = null

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  if (revokeTimer !== null) window.clearTimeout(revokeTimer)
})
</script>

<template>
  <div class="my-4">
    <div class="mb-2 flex items-center gap-2 text-[12px] text-muted-foreground">
      <span
        v-if="visuals.length"
        class="inline-flex items-center gap-1.5 rounded-full bg-surface px-2 py-0.5"
      >
        <ImageIcon class="size-3" />
        {{ visuals.length }} 张
      </span>
      <span
        v-if="credits"
        class="inline-flex items-center rounded-full bg-brand-soft px-2 py-0.5 text-brand"
      >
        {{ credits }} 积分
      </span>
    </div>

    <!--
      缩略图固定尺寸、按行折行，1 张到 N 张同一套规则。
      不用 grid 分列（列宽会跟着容器拉伸），也不做数量自适应：尺寸只由这里决定，
      布局怎么变都不影响卡片本身。
    -->
    <div v-if="visuals.length" class="flex flex-wrap gap-2">
      <div
        v-for="(item, index) in visuals"
        :key="item.id"
        class="group relative h-[150px] w-[175px] shrink-0 overflow-hidden rounded-lg border border-border bg-surface transition-shadow hover:shadow-[0_6px_20px_-6px_rgba(20,20,30,0.18)]"
      >
        <button
          type="button"
          class="absolute inset-0 cursor-zoom-in"
          @click="open(index)"
        >
          <AuthMedia
            :file-id="item.fileId"
            :src="item.src"
            :data="item.data"
            :media-type="item.mediaType"
            :alt="item.alt"
            :kind="item.kind === 'video' ? 'video' : 'image'"
            :controls="item.kind === 'video'"
            fit="cover"
            class="size-full"
          />
        </button>

        <!-- 常驻显示：悬停才出现的按钮在触屏上根本摸不到，图深图浅也容易看漏。
             图标固定用深色，不能跟着主题走——按钮底色恒为白，暗色主题下 text-foreground 也是白的。 -->
        <button
          type="button"
          class="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded-lg bg-white text-neutral-900 shadow-md ring-1 ring-black/15 transition-colors hover:bg-neutral-100"
          title="下载"
          @click.stop="download(item)"
        >
          <Download class="size-4" :stroke-width="2.2" />
        </button>

        <span
          v-if="visuals.length > 1"
          class="pointer-events-none absolute bottom-1 left-1 rounded bg-black/45 px-1 py-0.5 text-[10px] leading-none text-white backdrop-blur"
        >
          {{ index + 1 }}/{{ visuals.length }}
        </span>
      </div>
    </div>

    <div v-if="attachments.length" class="mt-2 flex flex-wrap gap-2">
      <FileAttachment
        v-for="item in attachments"
        :key="item.id"
        :name="item.name ?? 'file'"
        :size="item.size"
        :media-type="item.mediaType"
        :file-id="item.fileId"
        :data="item.data"
      />
    </div>

    <Teleport to="body">
      <div
        v-if="active"
        class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/70 px-4 py-14 backdrop-blur-sm sm:p-6"
        @click.self="close"
      >
        <button
          type="button"
          class="absolute right-4 top-4 grid size-9 place-items-center rounded-full bg-white/15 text-white transition-colors hover:bg-white/25 sm:right-5 sm:top-5"
          @click="close"
        >
          <X class="size-4" />
        </button>

        <button
          v-if="visuals.length > 1"
          type="button"
          class="absolute left-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white transition-colors hover:bg-white/25 sm:left-4"
          @click="step(-1)"
        >
          <ChevronLeft class="size-4" />
        </button>

        <div class="flex min-h-0 w-full max-w-[880px] flex-1 items-center justify-center overflow-hidden rounded-2xl bg-black">
          <AuthMedia
            :file-id="active.fileId"
            :src="active.src"
            :data="active.data"
            :media-type="active.mediaType"
            :alt="active.alt"
            :kind="active.kind === 'video' ? 'video' : 'image'"
            :controls="active.kind === 'video'"
            fit="contain"
            class="h-full max-h-full w-full"
          />
        </div>

        <button
          v-if="visuals.length > 1"
          type="button"
          class="absolute right-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white transition-colors hover:bg-white/25 sm:right-4"
          @click="step(1)"
        >
          <ChevronRight class="size-4" />
        </button>

        <!-- 提示词跟着图片走，窄屏可换行；过长时内部滚动，不再单行截断 -->
        <div
          v-if="active.alt || activeIndex !== null"
          class="flex w-full max-w-[880px] shrink-0 items-start gap-3 text-[12px] leading-5 text-white/80"
        >
          <p
            v-if="active.alt"
            class="max-h-[24vh] min-w-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words pr-1 [overflow-wrap:anywhere]"
          >
            {{ active.alt }}
          </p>
          <span v-if="activeIndex !== null" class="shrink-0 font-mono">
            {{ activeIndex + 1 }}/{{ visuals.length }}
          </span>
        </div>
      </div>
    </Teleport>
  </div>
</template>
