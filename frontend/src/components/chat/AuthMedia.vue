<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { Loader2 } from '@lucide/vue'

import { filesApi } from '@/api/files'
import { loadCachedImage } from '@/lib/mediaCache'

const props = withDefaults(
  defineProps<{
    fileId?: string | null
    src?: string | null
    data?: string | null
    mediaType?: string | null
    alt?: string | null
    kind?: 'image' | 'video'
    controls?: boolean
    fit?: 'cover' | 'contain'
    compact?: boolean
  }>(),
  {
    fileId: null,
    src: null,
    data: null,
    mediaType: null,
    alt: null,
    kind: 'image',
    controls: true,
    fit: 'cover',
    compact: false,
  },
)

const REFRESH_MARGIN_MS = 60_000
// 直链在有效期内复用，按 file_id 缓存，省掉每次挂载重新签一条
const linkCache = new Map<string, { url: string; expiresAt: number }>()

const resolved = ref<string | null>(null)
const loading = ref(false)
const failed = ref(false)
let controller: AbortController | null = null
let objectUrl: string | null = null
let fellBack = false

function cleanup(): void {
  controller?.abort()
  controller = null
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = null
  }
}

/** 字节下载兜底：宁可慢一点，也不要让图片直接消失。 */
async function loadBytes(): Promise<void> {
  if (!props.fileId) {
    failed.value = true
    return
  }
  loading.value = true
  const current = new AbortController()
  controller = current
  try {
    const blob = await filesApi.content(props.fileId, current.signal)
    if (current.signal.aborted) return
    objectUrl = URL.createObjectURL(blob)
    resolved.value = objectUrl
  } catch (error) {
    // 主动中断不算失败；真的取不到字节时要把 file_id 和原因留下来
    if (!current.signal.aborted) {
      console.warn(`媒体加载失败：file ${props.fileId}`, error)
      failed.value = true
    }
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

async function loadLink(): Promise<void> {
  if (!props.fileId) {
    failed.value = true
    return
  }
  const cached = linkCache.get(props.fileId)
  if (cached && cached.expiresAt - Date.now() > REFRESH_MARGIN_MS) {
    resolved.value = cached.url
    return
  }

  loading.value = true
  const current = new AbortController()
  controller = current
  try {
    const link = await filesApi.link(props.fileId, current.signal)
    if (current.signal.aborted) return
    linkCache.set(props.fileId, { url: link.url, expiresAt: Date.parse(link.expires_at) })
    resolved.value = link.url
  } catch {
    if (!current.signal.aborted) await loadBytes()
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

/** 图片优先走持久缓存：打开历史会话时不再重新下载同一张图。 */
async function loadImage(): Promise<void> {
  if (!props.fileId) {
    failed.value = true
    return
  }
  loading.value = true
  const current = new AbortController()
  controller = current
  try {
    const blob = await loadCachedImage(props.fileId)
    if (current.signal.aborted) return
    objectUrl = URL.createObjectURL(blob)
    resolved.value = objectUrl
  } catch {
    // 缓存与同源取字节都失败时再退回直链，别让一张图卡住整个会话
    if (!current.signal.aborted) await loadLink()
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

async function resolve(): Promise<void> {
  cleanup()
  fellBack = false
  failed.value = false
  resolved.value = null

  if (props.src) {
    resolved.value = props.src
    return
  }
  if (props.data) {
    const mime = props.mediaType || (props.kind === 'image' ? 'image/png' : 'video/mp4')
    resolved.value = `data:${mime};base64,${props.data}`
    return
  }
  if (props.kind === 'image') {
    await loadImage()
    return
  }
  await loadLink()
}

function onMediaError(): void {
  // 直链可能刚好跨过了签名窗口，退回字节下载再试一次
  if (fellBack || !props.fileId) {
    failed.value = true
    return
  }
  fellBack = true
  void loadBytes()
}

watch(() => [props.fileId, props.src, props.data, props.mediaType], resolve, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<template>
  <div
    class="relative flex items-center justify-center overflow-hidden bg-surface-strong/40"
    :class="compact ? 'min-h-0 min-w-0' : 'min-h-16 min-w-16'"
  >
    <img
      v-if="resolved && kind === 'image'"
      :src="resolved"
      :alt="alt || '图片'"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      class="h-full w-full"
      :class="fit === 'contain' ? 'object-contain' : 'object-cover'"
      @error="onMediaError"
    >
    <video
      v-else-if="resolved && kind === 'video'"
      :src="resolved"
      :controls="controls"
      playsinline
      preload="metadata"
      referrerpolicy="no-referrer"
      class="h-full w-full"
      :class="fit === 'contain' ? 'object-contain' : 'object-cover'"
      @error="onMediaError"
    />
    <div v-else-if="failed" class="grid place-items-center px-3 py-4 text-center text-[11.5px] text-muted-foreground">
      无法加载{{ kind === 'image' ? '图片' : '视频' }}
    </div>
    <div v-else class="absolute inset-0 grid place-items-center text-muted-foreground">
      <Loader2 class="size-4 animate-spin" />
    </div>
  </div>
</template>
