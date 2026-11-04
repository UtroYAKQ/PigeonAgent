<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, FileText, Loader2 } from '@lucide/vue'

import { filesApi } from '@/api/files'
import { TooltipHint } from '@/components/ui/tooltip'
import { formatBytes } from '@/lib/format'
import { toast } from 'vue-sonner'

const props = defineProps<{
  name: string
  size?: number
  mediaType?: string
  fileId?: string | null
  data?: string | null
}>()

const downloading = ref(false)

const extension = computed(() => {
  const parts = props.name.split('.')
  return parts.length > 1 ? parts.pop()!.toUpperCase().slice(0, 4) : 'FILE'
})

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
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = props.name
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    toast.error('下载失败，请重试')
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <TooltipHint :text="`下载 ${name}`">
    <button
      type="button"
      class="group/file flex max-w-[300px] items-center gap-2.5 rounded-lg border border-border bg-background px-2.5 py-2 text-left transition-colors hover:bg-surface"
      @click="download"
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
      <span class="grid size-6 shrink-0 place-items-center text-muted-foreground/70 group-hover/file:text-foreground">
        <Loader2 v-if="downloading" class="size-3.5 animate-spin" />
        <Download v-else class="size-3.5" />
      </span>
    </button>
  </TooltipHint>
</template>
