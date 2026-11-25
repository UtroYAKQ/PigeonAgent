<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { Download, Eye, FileText, Loader2 } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { filesApi } from '@/api/files'
import { TooltipHint } from '@/components/ui/tooltip'
import { saveBlob } from '@/lib/fileDownload'
import { formatBytes } from '@/lib/format'
import { PANEL_HOST_KEY } from '@/lib/panelHost'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  mediaType?: string
  fileId?: string | null
  data?: string | null
  previewable?: boolean
}>(), {
  fileId: null,
  data: null,
  previewable: false,
})

const chat = useChatStore()
const panels = usePanelStore()
const panelHost = inject(PANEL_HOST_KEY, false)
const downloading = ref(false)

const canPreview = computed(() => (
  props.previewable
  && panelHost
  && Boolean(props.fileId)
  && Boolean(chat.currentSessionId)
))

const extension = computed(() => {
  const parts = props.name.split('.')
  return parts.length > 1 ? parts.pop()!.toUpperCase().slice(0, 4) : 'FILE'
})

async function preview(): Promise<void> {
  if (!canPreview.value || !props.fileId || !chat.currentSessionId) return
  panels.openFile({
    sessionId: chat.currentSessionId,
    title: props.name,
    fileId: props.fileId,
    mediaType: props.mediaType ?? null,
    size: props.size ?? null,
    sourceId: props.fileId,
  })
}

async function download(): Promise<void> {
  if (downloading.value) return
  downloading.value = true
  try {
    let blob: Blob
    if (props.fileId) {
      blob = await filesApi.content(props.fileId)
    } else if (props.data) {
      const response = await fetch(`data:${props.mediaType || 'application/octet-stream'};base64,${props.data}`)
      blob = await response.blob()
    } else {
      return
    }
    saveBlob(blob, props.name)
  } catch {
    toast.error('下载失败，请重试')
  } finally {
    downloading.value = false
  }
}

function open(): void {
  if (canPreview.value) void preview()
  else void download()
}
</script>

<template>
  <div
    class="group/file flex max-w-[320px] items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-2 transition-colors hover:bg-surface"
  >
    <button
      type="button"
      class="flex min-w-0 flex-1 items-center gap-2.5 text-left"
      :title="canPreview ? `预览 ${name}` : `下载 ${name}`"
      @click="open"
    >
      <span class="grid size-8 shrink-0 place-items-center rounded-md bg-surface text-muted-foreground">
        <FileText class="size-4" :stroke-width="1.8" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-[12.5px] font-medium leading-4 text-foreground">{{ name }}</span>
        <span class="mt-0.5 block text-[11px] leading-4 text-muted-foreground">
          {{ extension }}<template v-if="size"> · {{ formatBytes(size) }}</template>
        </span>
      </span>
    </button>

    <div class="flex shrink-0 items-center gap-0.5">
      <TooltipHint v-if="canPreview" text="预览">
        <button
          type="button"
          class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-strong hover:text-foreground"
          aria-label="预览文件"
          @click="preview"
        >
          <Eye class="size-4" :stroke-width="1.8" />
        </button>
      </TooltipHint>
      <TooltipHint text="下载">
        <button
          type="button"
          class="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-strong hover:text-foreground"
          aria-label="下载文件"
          :disabled="downloading"
          @click="download"
        >
          <Loader2 v-if="downloading" class="size-3.5 animate-spin" />
          <Download v-else class="size-3.5" :stroke-width="1.8" />
        </button>
      </TooltipHint>
    </div>
  </div>
</template>