<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AlertTriangle, Loader2 } from '@lucide/vue'

import { adminApi } from '@/api/admin'
import { CodeBlock } from '@/components/ai-elements/code-block'
import MarkdownMessage from '@/components/chat/MarkdownMessage.vue'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { FilePreviewTarget } from '@/lib/fileScope'
import { formatBytes } from '@/lib/format'
import { guardPreviewDocument } from '@/lib/previewDocument'
import { fileLanguage } from '@/lib/tools'

type PreviewKind = 'image' | 'video' | 'pdf' | 'html' | 'markdown' | 'code' | 'binary'

const props = defineProps<{
  open: boolean
  target: FilePreviewTarget | null
}>()
const emit = defineEmits<{ 'update:open': [boolean] }>()

const MAX_TEXT_BYTES = 2 * 1024 * 1024
const MAX_PDF_BYTES = 30 * 1024 * 1024
const TEXTUAL_TYPES = new Set([
  'application/json', 'application/javascript', 'application/typescript', 'application/xml',
  'application/xhtml+xml', 'application/x-yaml', 'application/yaml', 'application/toml', 'application/x-sh',
])
const CODE_EXTENSIONS = new Set([
  'txt','csv','log','ini','env','conf','ts','tsx','js','jsx','mjs','cjs','vue','css','scss','less',
  'json','yml','yaml','toml','py','sh','bash','go','rs','java','c','h','cpp','cc','hpp','cs','php','rb','swift','kt','sql','xml','svg',
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
  const mediaType = (props.target?.mediaType || '').toLowerCase()
  const extension = extensionOf(props.target?.name || '')
  if (mediaType.startsWith('image/')) return 'image'
  if (mediaType.startsWith('video/')) return 'video'
  if (mediaType === 'application/pdf' || extension === 'pdf') return 'pdf'
  if (mediaType === 'text/html' || extension === 'html' || extension === 'htm') return 'html'
  if (mediaType === 'text/markdown' || mediaType === 'text/x-markdown' || extension === 'md' || extension === 'markdown') return 'markdown'
  if (mediaType.startsWith('text/') || TEXTUAL_TYPES.has(mediaType) || CODE_EXTENSIONS.has(extension)) return 'code'
  return 'binary'
})
const needsContent = computed(() => ['image','video','pdf','html','markdown','code'].includes(kind.value))
const sourceLanguage = computed(() => kind.value === 'html' ? 'html' : fileLanguage(props.target?.name || '', text.value))
const previewSrcdoc = computed(() => kind.value === 'html' ? guardPreviewDocument(text.value) : '')
const meta = computed(() => {
  const parts: string[] = []
  if (props.target?.size) parts.push(formatBytes(props.target.size))
  if (props.target?.mediaType) parts.push(props.target.mediaType)
  return parts.join(' ? ')
})

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
  if (!props.open || !props.target?.fileId || !needsContent.value) return

  loading.value = true
  const current = new AbortController()
  controller = current
  try {
    const blob = await adminApi.fileContent(props.target.fileId, current.signal)
    if (current.signal.aborted) return
    if (kind.value === 'image' || kind.value === 'video' || kind.value === 'pdf') {
      const max = kind.value === 'pdf' ? MAX_PDF_BYTES : Number.MAX_SAFE_INTEGER
      if (blob.size > max) { error.value = '???????????'; return }
      objectUrl.value = URL.createObjectURL(blob)
      return
    }
    if (blob.size > MAX_TEXT_BYTES) { error.value = '???????????'; return }
    text.value = await blob.text()
  } catch {
    if (!current.signal.aborted) error.value = '文件加载失败，请重试'
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => [props.open, props.target?.fileId], load, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="max-w-5xl gap-0 overflow-hidden p-0">
      <DialogHeader class="border-b border-border px-4 py-3 pr-12 text-left">
        <DialogTitle class="truncate text-sm">{{ target?.name || '????' }}</DialogTitle>
        <DialogDescription class="truncate text-[11px]">{{ meta || '???????' }}</DialogDescription>
      </DialogHeader>
      <div class="h-[75vh] min-h-[360px] bg-background">
        <div v-if="loading" class="grid h-full place-items-center text-muted-foreground"><Loader2 class="size-4 animate-spin" /></div>
        <div v-else-if="error" class="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
          <span class="grid size-9 place-items-center rounded-full border border-border text-muted-foreground"><AlertTriangle class="size-4" /></span>
          <p class="text-[12.5px] text-muted-foreground">{{ error }}</p>
        </div>
        <img v-else-if="kind === 'image' && objectUrl" :src="objectUrl" :alt="target?.name || '??'" class="h-full w-full object-contain" />
        <video v-else-if="kind === 'video' && objectUrl" :src="objectUrl" controls playsinline class="h-full w-full bg-black object-contain" />
        <iframe v-else-if="kind === 'pdf' && objectUrl" :src="objectUrl" class="h-full w-full bg-white" :title="target?.name || 'PDF'" />
        <iframe v-else-if="kind === 'html'" :srcdoc="previewSrcdoc" sandbox="allow-scripts" referrerpolicy="no-referrer" class="h-full w-full bg-white" :title="target?.name || 'HTML'" />
        <div v-else-if="kind === 'code'" class="h-full overflow-hidden bg-code">
          <CodeBlock :code="text" :language="sourceLanguage" show-line-numbers class="panel-code pigeon-code h-full bg-code" />
        </div>
        <div v-else-if="kind === 'markdown'" class="h-full overflow-y-auto px-6 py-5"><MarkdownMessage :content="text" /></div>
        <div v-else class="flex h-full items-center justify-center px-6 text-center text-[12.5px] text-muted-foreground">????????????</div>
      </div>
    </DialogContent>
  </Dialog>
</template>
