<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AlertTriangle, FileText, Loader2 } from '@lucide/vue'

import { filesApi } from '@/api/files'
import { CodeBlock } from '@/components/ai-elements/code-block'
import { guardPreviewDocument } from '@/lib/previewDocument'
import { fileLanguage } from '@/lib/tools'
import type { PanelTab } from '@/types/panel'
import AuthMedia from './AuthMedia.vue'
import MarkdownMessage from './MarkdownMessage.vue'

type PreviewKind = 'image' | 'video' | 'pdf' | 'html' | 'markdown' | 'code' | 'binary'

const props = defineProps<{ tab: PanelTab }>()

const MAX_TEXT_BYTES = 2 * 1024 * 1024
const MAX_PDF_BYTES = 30 * 1024 * 1024
const TEXTUAL_TYPES = new Set([
  'application/json',
  'application/javascript',
  'application/typescript',
  'application/xml',
  'application/xhtml+xml',
  'application/x-yaml',
  'application/yaml',
  'application/toml',
  'application/x-sh',
])
const CODE_EXTENSIONS = new Set([
  'txt', 'csv', 'log', 'ini', 'env', 'conf',
  'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'vue', 'css', 'scss', 'less',
  'json', 'yml', 'yaml', 'toml', 'py', 'sh', 'bash', 'go', 'rs', 'java',
  'c', 'h', 'cpp', 'cc', 'hpp', 'cs', 'php', 'rb', 'swift', 'kt', 'sql',
  'xml', 'svg',
])

const text = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const objectUrl = ref<string | null>(null)
let controller: AbortController | null = null

function extensionOf(name: string): string {
  const tail = name.includes('.') ? name.split('.').pop() : ''
  return (tail || '').toLowerCase()
}

const kind = computed<PreviewKind>(() => {
  const mediaType = (props.tab.mediaType || '').toLowerCase()
  const extension = extensionOf(props.tab.title)
  if (mediaType.startsWith('image/')) return 'image'
  if (mediaType.startsWith('video/')) return 'video'
  if (mediaType === 'application/pdf' || extension === 'pdf') return 'pdf'
  if (mediaType === 'text/html' || extension === 'html' || extension === 'htm') return 'html'
  if (
    mediaType === 'text/markdown'
    || mediaType === 'text/x-markdown'
    || extension === 'md'
    || extension === 'markdown'
  ) return 'markdown'
  if (mediaType.startsWith('text/') || TEXTUAL_TYPES.has(mediaType) || CODE_EXTENSIONS.has(extension)) {
    return 'code'
  }
  return 'binary'
})

const needsContent = computed(() => kind.value === 'pdf' || kind.value === 'html'
  || kind.value === 'markdown' || kind.value === 'code')
const sourceLanguage = computed(() => (
  kind.value === 'html' ? 'html' : fileLanguage(props.tab.title, text.value)
))
const previewSrcdoc = computed(() => (
  kind.value === 'html' ? guardPreviewDocument(text.value) : ''
))
function cleanup(): void {
  controller?.abort()
  controller = null
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = null
  }
}

async function load(): Promise<void> {
  cleanup()
  text.value = ''
  error.value = null
  if (!needsContent.value || !props.tab.fileId) return

  loading.value = true
  const current = new AbortController()
  controller = current
  try {
    const blob = await filesApi.content(props.tab.fileId, current.signal)
    if (current.signal.aborted) return
    if (kind.value === 'pdf') {
      if (blob.size > MAX_PDF_BYTES) {
        error.value = '文件过大，请下载后查看'
        return
      }
      objectUrl.value = URL.createObjectURL(blob)
      return
    }
    if (blob.size > MAX_TEXT_BYTES) {
      error.value = '文件过大，请下载后查看'
      return
    }
    text.value = await blob.text()
  } catch (caught) {
    if (!current.signal.aborted) {
      console.warn(`文件预览加载失败：${props.tab.fileId}`, caught)
      error.value = '文件加载失败，请重试'
    }
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => [props.tab.id, props.tab.fileId], load, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background">
    <div class="min-h-0 flex-1">
      <div v-if="loading" class="grid h-full place-items-center text-muted-foreground">
        <Loader2 class="size-4 animate-spin" />
      </div>

      <div
        v-else-if="error"
        class="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
      >
        <span class="grid size-9 place-items-center rounded-full border border-border text-muted-foreground">
          <AlertTriangle class="size-4" />
        </span>
        <p class="text-[12.5px] text-muted-foreground">{{ error }}</p>
      </div>

      <AuthMedia
        v-else-if="kind === 'image' || kind === 'video'"
        :file-id="tab.fileId"
        :media-type="tab.mediaType"
        :kind="kind"
        fit="contain"
        class="h-full w-full"
      />

      <iframe
        v-else-if="kind === 'pdf' && objectUrl"
        :src="objectUrl"
        class="h-full w-full bg-white"
        :title="tab.title"
      />

      <iframe
        v-else-if="kind === 'html'"
        :srcdoc="previewSrcdoc"
        sandbox="allow-scripts"
        referrerpolicy="no-referrer"
        class="h-full w-full bg-white"
        :title="tab.title"
      />

      <div v-else-if="kind === 'code'" class="h-full overflow-hidden bg-code">
        <CodeBlock
          :code="text"
          :language="sourceLanguage"
          show-line-numbers
          class="panel-code pigeon-code h-full bg-code"
        />
      </div>

      <div v-else-if="kind === 'markdown'" class="h-full overflow-y-auto px-6 py-5">
        <MarkdownMessage :content="text" />
      </div>

      <div
        v-else
        class="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
      >
        <span class="grid size-10 place-items-center rounded-xl border border-border bg-surface text-muted-foreground">
          <FileText class="size-4" />
        </span>
        <p class="text-[12.5px] font-medium">{{ tab.title }}</p>
        <p class="text-[11.5px] leading-5 text-muted-foreground">这个类型暂不支持直接预览</p>
      </div>
    </div>
  </div>
</template>