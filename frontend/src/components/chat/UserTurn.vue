<script setup lang="ts">
import { computed } from 'vue'
import { toast } from 'vue-sonner'
import { Check, Copy, Pencil } from '@lucide/vue'

import { TooltipHint } from '@/components/ui/tooltip'
import { useCopyFeedback } from '@/composables/useCopyFeedback'
import type { TurnView } from '@/lib/turnModel'
import { useChatStore } from '@/stores/chat'
import type { SessionRun } from '@/types/api'
import AuthMedia from './AuthMedia.vue'
import FileAttachment from './FileAttachment.vue'

const props = defineProps<{
  run: SessionRun
  view: TurnView
}>()

const chat = useChatStore()
const { copied, copyText } = useCopyFeedback()

const hasMedia = computed(() => props.view.userImages.length > 0 || props.view.userVideos.length > 0)
const hasAttachments = computed(() => hasMedia.value || props.view.userResources.length > 0)
const canEdit = computed(() => !chat.busy && !chat.hasPendingInterrupts)

async function copy(): Promise<void> {
  const text = [
    props.view.userText,
    ...props.view.userResources.map(item => item.name),
  ].filter(Boolean).join('\n')
  await copyText(text, () => toast.error('复制失败'))
}

function startEdit(): void {
  if (!canEdit.value) return
  chat.beginEditing(props.run)
}
</script>

<template>
  <div class="flex flex-col items-end">
    <div class="w-fit max-w-[min(100%,560px)] rounded-[14px] bg-surface px-4 py-2.5">
      <div v-if="hasMedia" class="flex flex-wrap gap-2" :class="hasAttachments && (view.userText || view.userResources.length) ? 'mb-2.5' : ''">
        <TooltipHint
          v-for="image in view.userImages"
          :key="image.id"
          :text="image.alt || '图片'"
        >
          <div class="h-40 w-56 max-w-full overflow-hidden rounded-lg border border-border">
            <AuthMedia
              kind="image"
              fit="contain"
              :file-id="image.file_id"
              :media-type="image.media_type"
              :alt="image.alt"
              class="h-full w-full"
            />
          </div>
        </TooltipHint>
        <div
          v-for="video in view.userVideos"
          :key="video.id"
          class="h-40 w-56 max-w-full overflow-hidden rounded-lg border border-border"
        >
          <AuthMedia
            kind="video"
            :file-id="video.file_id"
            :media-type="video.media_type"
            fit="contain"
            class="h-full w-full"
          />
        </div>
      </div>

      <p
        v-if="view.userText"
        class="whitespace-pre-wrap break-words text-[16px] leading-[1.7] text-foreground"
        :class="hasAttachments ? 'px-1' : ''"
      >
        {{ view.userText }}
      </p>

      <div
        v-if="view.userResources.length"
        class="flex flex-wrap gap-2"
        :class="view.userText || hasMedia ? 'mt-2.5 px-1' : ''"
      >
        <FileAttachment
          v-for="resource in view.userResources"
          :key="resource.id"
          :name="resource.name"
          :size="resource.size"
          :media-type="resource.media_type"
          :file-id="resource.file_id"
        />
      </div>
    </div>

    <div
      class="mt-1 flex items-center gap-0.5 opacity-100 transition-opacity duration-150 sm:opacity-0 sm:group-hover/turn:opacity-100"
    >
      <TooltipHint text="在输入框中编辑">
        <button
          type="button"
          class="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground disabled:opacity-40"
          aria-label="在输入框中编辑"
          :disabled="!canEdit"
          @click="startEdit"
        >
          <Pencil class="size-4" />
        </button>
      </TooltipHint>
      <TooltipHint text="复制提问">
        <button
          type="button"
          class="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
          aria-label="复制提问"
          @click="copy"
        >
          <Check v-if="copied" class="size-4" />
          <Copy v-else class="size-4" />
        </button>
      </TooltipHint>
    </div>
  </div>
</template>
