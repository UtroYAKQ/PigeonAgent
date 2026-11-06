<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import {
  ArrowUp,
  Check,
  FileText,
  Film,
  Globe2,
  Loader2,
  Mic,
  Paperclip,
  PencilLine,
  Square,
  X,
} from '@lucide/vue'

import { TooltipHint } from '@/components/ui/tooltip'
import { useDraftAttachments } from '@/composables/useDraftAttachments'
import { useSpeechInput } from '@/composables/useSpeechInput'
import { errorMessage } from '@/lib/http'
import { formatBytes } from '@/lib/format'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import type {
  DraftAttachment,
  ImageItem,
  ResourceItem,
  VideoItem,
} from '@/types/api'
import AuthMedia from './AuthMedia.vue'
import CapabilityToggle from './CapabilityToggle.vue'
import FileAttachment from './FileAttachment.vue'
import ImageModelPicker from './ImageModelPicker.vue'
import ModelPicker from './ModelPicker.vue'
import ThinkingLevelPicker from './ThinkingLevelPicker.vue'

const props = withDefaults(defineProps<{ hero?: boolean; showDisclaimer?: boolean }>(), {
  hero: false,
  showDisclaimer: true,
})

const chat = useChatStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const text = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const sending = ref(false)
const heightAnimating = ref(false)
const draftBeforeEdit = ref('')
const {
  attachments,
  uploading,
  hasReady,
  addFiles,
  removeAttachment,
  clearAttachments,
  takeAttachments,
} = useDraftAttachments()
let restoringEdit = false
let heightTimer: number | null = null

const isEditing = computed(() => Boolean(chat.editingRun))
const editingMedia = computed<Array<ImageItem | VideoItem>>(() => {
  const run = chat.editingRun
  if (!run) return []
  return run.content.filter(
    (item): item is ImageItem | VideoItem =>
      (item.type === 'image' || item.type === 'video') && item.role === 'user',
  )
})
const editingResources = computed<ResourceItem[]>(() => {
  const run = chat.editingRun
  if (!run) return []
  return run.content.filter(
    (item): item is ResourceItem => item.type === 'resource' && item.role === 'user',
  )
})
const hasEditingAttachments = computed(
  () => editingMedia.value.length > 0 || editingResources.value.length > 0,
)

watch(
  () => chat.editingRun?.id,
  async (id, previous) => {
    const element = textarea.value
    if (element) element.style.height = `${element.getBoundingClientRect().height}px`
    animateHeight()
    if (id) {
      if (!previous) draftBeforeEdit.value = text.value
      text.value = chat.editingText
      clearAttachments()
    } else if (previous) {
      text.value = restoringEdit ? draftBeforeEdit.value : ''
      draftBeforeEdit.value = ''
      restoringEdit = false
    }
    await nextTick()
    resize(true)
    scheduleHeightAnimationEnd()
    textarea.value?.focus()
  },
)

const canSend = computed(() => {
  if (sending.value || !chat.currentModelId) return false
  if (isEditing.value) return !chat.busy && text.value.trim().length > 0
  if (chat.busy || chat.hasPendingInterrupts) return false
  return !uploading.value && (text.value.trim().length > 0 || hasReady.value)
})

const hasModel = computed(() => chat.modelsLoaded && Boolean(chat.currentModelId))
const placeholder = computed(() => {
  if (!hasModel.value) return '暂无可用模型'
  if (isEditing.value) return '编辑消息…'
  if (chat.hasPendingInterrupts) return '请先处理上方的确认卡片'
  return props.hero ? '有问题，尽管问' : '给 PigeonAgent 发送消息'
})

function animateHeight(): void {
  heightAnimating.value = true
  if (heightTimer !== null) {
    window.clearTimeout(heightTimer)
    heightTimer = null
  }
}

function finishHeightAnimation(): void {
  heightAnimating.value = false
  if (heightTimer !== null) {
    window.clearTimeout(heightTimer)
    heightTimer = null
  }
}

function scheduleHeightAnimationEnd(): void {
  if (heightTimer !== null) window.clearTimeout(heightTimer)
  heightTimer = window.setTimeout(finishHeightAnimation, 320)
}

function resize(animate = false): void {
  const element = textarea.value
  if (!element) return
  if (!animate) {
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
    return
  }

  const start = element.getBoundingClientRect().height
  const transition = element.style.transition
  element.style.transition = 'none'
  element.style.height = 'auto'
  const target = Math.min(element.scrollHeight, 200)
  element.style.height = `${start}px`
  void element.offsetHeight
  element.style.transition = transition
  element.style.height = `${target}px`
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files) void addFiles(Array.from(input.files))
  input.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (isEditing.value) return
  if (event.dataTransfer?.files?.length) {
    void addFiles(Array.from(event.dataTransfer.files))
  }
}

function onPaste(event: ClipboardEvent): void {
  if (isEditing.value) return
  const files = Array.from(event.clipboardData?.files ?? []).filter(file => file.type.startsWith('image/'))
  if (files.length) {
    event.preventDefault()
    void addFiles(files)
  }
}

function appendSpeech(segment: string): void {
  const base = text.value.trimEnd()
  const cjk = /[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]/
  const joiner = base && !/\s$/.test(base) && !cjk.test(base.slice(-1)) && !cjk.test(segment.slice(0, 1))
    ? ' '
    : ''
  text.value = `${base}${joiner}${segment}`
  void nextTick(() => {
    resize()
    textarea.value?.focus()
  })
}

const {
  supported: speechSupported,
  listening: speechListening,
  stop: stopSpeech,
  toggle: toggleSpeech,
} = useSpeechInput({
  onFinal: appendSpeech,
  onError: message => toast.error('语音识别失败', { description: message }),
})

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && speechListening.value) {
    event.preventDefault()
    stopSpeech()
    return
  }
  if (event.key === 'Escape' && isEditing.value) {
    event.preventDefault()
    cancelEdit()
    return
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    const needsModifier = ui.sendShortcut === 'ctrl-enter'
    const hasModifier = event.ctrlKey || event.metaKey
    if (needsModifier && !hasModifier) return
    event.preventDefault()
    void submit()
  }
}

function cancelEdit(): void {
  if (!isEditing.value) return
  restoringEdit = true
  chat.cancelEditing()
}

function toggleWebSearch(): void {
  if (!chat.webSearchAvailable) return
  chat.setWebSearchEnabled(!chat.webSearchEnabled)
}

async function submit(): Promise<void> {
  if (!canSend.value) return
  if (speechListening.value) stopSpeech()
  sending.value = true
  try {
    if (isEditing.value && chat.editingRun) {
      await chat.editMessage(chat.editingRun, text.value)
      if (textarea.value) textarea.value.style.height = 'auto'
      return
    }
    const outgoing = text.value
    const files = takeAttachments()
    const outcome = await chat.sendMessage({ text: outgoing, attachments: files })
    if (outcome.joinedActiveRun) {
      // 另一个标签页正在生成：已接入观看，消息文本留在这里，这轮结束后可直接再发
      toast.info('已有回复正在生成，已接入观看；这条消息还留在输入框里')
    } else {
      text.value = ''
      clearAttachments()
      if (textarea.value) textarea.value.style.height = 'auto'
    }
    if (route.params.id !== outcome.sessionId) {
      await router.replace(`/c/${outcome.sessionId}`)
    }
  } catch (error) {
    toast.error(isEditing.value ? '保存失败' : '发送失败', { description: errorMessage(error) })
  } finally {
    sending.value = false
  }
}

async function stop(): Promise<void> {
  try {
    await chat.cancelRun()
  } catch (error) {
    toast.error('停止失败', { description: errorMessage(error) })
  }
}

function retryUpload(item: DraftAttachment): void {
  removeAttachment(item.localId)
  void addFiles([item.file])
}

onBeforeUnmount(() => {
  clearAttachments()
  if (heightTimer !== null) window.clearTimeout(heightTimer)
})
</script>

<template>
  <div class="w-full">
    <div
      class="relative rounded-[26px] border bg-background transition-[border-color,background-color,box-shadow] duration-150"
      :class="[
        dragging ? 'border-brand/60 bg-brand-soft' : 'border-input/90 hover:border-foreground/20',
        'focus-within:border-foreground/25',
        props.hero ? 'bg-background' : '',
      ]"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <div v-if="attachments.length && !isEditing" class="flex flex-wrap gap-2 px-3 pt-3">
        <div
          v-for="item in attachments"
          :key="item.localId"
          class="group/attachment relative flex items-center gap-2 rounded-lg border border-border bg-surface py-1.5 pl-1.5 pr-2.5"
          :class="item.kind === 'resource' ? 'max-w-[240px]' : ''"
        >
          <img
            v-if="item.kind === 'image' && item.previewUrl"
            :src="item.previewUrl"
            :alt="item.file.name"
            class="size-9 rounded-md object-cover"
          >
          <div v-else class="grid size-9 place-items-center rounded-md bg-surface-strong text-muted-foreground">
            <Film v-if="item.kind === 'video'" class="size-4" />
            <FileText v-else class="size-4" />
          </div>

          <div class="min-w-0">
            <p class="truncate text-[12.5px] font-medium leading-4 text-foreground">{{ item.file.name }}</p>
            <p class="mt-0.5 flex items-center gap-1 text-[11px] leading-4 text-muted-foreground">
              <template v-if="item.status === 'uploading'">上传中 {{ item.progress }}%</template>
              <template v-else-if="item.status === 'error'">
                <button type="button" class="text-destructive underline-offset-2 hover:underline" @click="retryUpload(item)">上传失败，重试</button>
              </template>
              <template v-else>{{ formatBytes(item.record?.size ?? item.file.size) }}</template>
            </p>
          </div>

          <button
            type="button"
            class="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-border bg-background text-muted-foreground opacity-100 transition-opacity hover:text-foreground sm:opacity-0 sm:group-hover/attachment:opacity-100"
            aria-label="移除附件"
            @click="removeAttachment(item.localId)"
          >
            <X class="size-3" />
          </button>

          <div
            v-if="item.status === 'uploading'"
            class="absolute inset-x-2 bottom-0 h-px overflow-hidden rounded-full bg-border"
          >
            <div class="h-full bg-brand transition-[width] duration-200" :style="{ width: `${item.progress}%` }" />
          </div>
        </div>
      </div>

      <Transition name="edit-bar">
        <div v-if="isEditing" class="edit-bar">
          <div>
            <div class="flex items-center gap-2 px-4 pb-1.5 pt-3 text-[11.5px] text-muted-foreground sm:px-5">
              <PencilLine class="size-3.5 shrink-0" />
              <span class="min-w-0 truncate">正在编辑消息</span>
              <button
                type="button"
                class="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11.5px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
                @click="cancelEdit"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      </Transition>

      <Transition name="edit-attachments">
        <div v-if="isEditing && hasEditingAttachments" class="edit-attachments">
          <div>
            <div class="flex flex-wrap items-center gap-2 px-4 pb-1 pt-2 sm:px-5">
              <TooltipHint
                v-for="item in editingMedia"
                :key="item.id"
                :text="item.alt || (item.type === 'image' ? '原消息图片' : '原消息视频')"
              >
                <div class="relative h-20 w-28 shrink-0 overflow-hidden rounded-lg border border-border bg-surface">
                  <AuthMedia
                    :kind="item.type"
                    :file-id="item.file_id"
                    :media-type="item.media_type"
                    :alt="item.alt"
                    fit="contain"
                    :controls="false"
                    class="h-full w-full"
                  />
                  <span
                    v-if="item.type === 'video'"
                    class="pointer-events-none absolute bottom-1 left-1 inline-flex items-center gap-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white"
                  >
                    <Film class="size-2.5" />
                    视频
                  </span>
                </div>
              </TooltipHint>
              <FileAttachment
                v-for="resource in editingResources"
                :key="resource.id"
                :name="resource.name"
                :size="resource.size"
                :media-type="resource.media_type"
                :file-id="resource.file_id"
              />
            </div>
          </div>
        </div>
      </Transition>

      <textarea
        ref="textarea"
        v-model="text"
        rows="1"
        :placeholder="placeholder"
        :disabled="!hasModel"
        class="scrollbar-none block max-h-[200px] min-h-[28px] w-full resize-none border-0 bg-transparent px-4 pt-3.5 text-[16px] leading-[1.6] text-foreground outline-none placeholder:text-muted-foreground/80 disabled:cursor-not-allowed sm:px-5"
        :class="heightAnimating ? 'edit-height' : ''"
        @input="resize()"
        @keydown="onKeydown"
        @paste="onPaste"
      />

      <div class="flex flex-wrap items-center gap-1.5 gap-y-2 px-2.5 pb-2">
        <TooltipHint :text="isEditing ? '编辑消息时不能添加附件' : '添加附件'">
          <button
            type="button"
            class="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface hover:text-foreground disabled:opacity-40"
            :aria-label="isEditing ? '编辑消息时不能添加附件' : '添加附件'"
            :disabled="chat.busy || isEditing"
            @click="fileInput?.click()"
          >
            <Paperclip class="size-4" />
          </button>
        </TooltipHint>
        <input v-if="!isEditing" ref="fileInput" type="file" multiple class="hidden" @change="onFileChange">
        <ModelPicker />
        <CapabilityToggle
          v-if="chat.webSearchAvailable"
          :active="chat.effectiveWebSearch"
          label="联网"
          @toggle="toggleWebSearch"
        >
          <Globe2 class="size-3.5" :stroke-width="1.8" />
        </CapabilityToggle>
        <ImageModelPicker v-if="chat.imageGenerationAvailable" />
        <div class="ml-auto flex items-center gap-1.5">
          <span v-if="uploading" class="mr-1 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Loader2 class="size-3 animate-spin" />
            上传中
          </span>
          <ThinkingLevelPicker />
          <TooltipHint :text="speechSupported ? (speechListening ? '停止语音输入' : '语音输入') : '当前浏览器不支持语音识别'">
            <button
              type="button"
              class="grid size-8 place-items-center rounded-full transition-colors disabled:opacity-40"
              :class="speechListening
                ? 'bg-brand-soft text-brand'
                : 'text-muted-foreground hover:bg-surface hover:text-foreground'"
              :disabled="!speechSupported || !hasModel"
              :aria-pressed="speechListening"
              aria-label="语音输入"
              @click="toggleSpeech"
            >
              <Mic class="size-4" :class="speechListening ? 'animate-pulse' : ''" />
            </button>
          </TooltipHint>
          <button
            v-if="chat.busy"
            type="button"
            class="grid size-8 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-85"
            :aria-label="chat.cancelling ? '正在停止' : '停止生成'"
            :disabled="chat.cancelling"
            @click="stop"
          >
            <Loader2 v-if="chat.cancelling" class="size-3.5 animate-spin" />
            <Square v-else class="size-3 fill-current" />
          </button>
          <button
            v-else
            type="button"
            class="grid size-8 place-items-center rounded-full bg-primary text-primary-foreground transition-[opacity,transform] duration-150 hover:opacity-85 active:scale-95 disabled:opacity-25"
            :aria-label="isEditing ? '保存修改' : '发送消息'"
            :disabled="!canSend"
            @click="submit"
          >
            <Loader2 v-if="sending" class="size-4 animate-spin" />
            <Check v-else-if="isEditing" class="size-4" :stroke-width="2.2" />
            <ArrowUp v-else class="size-4" :stroke-width="2.2" />
          </button>
        </div>
      </div>
    </div>

    <p v-if="showDisclaimer" class="relative mt-2.5 h-5 text-center text-[11.5px] leading-5 text-muted-foreground/70">
      <span
        class="absolute inset-x-0 top-0 transition-opacity duration-200"
        :class="isEditing ? 'opacity-0' : 'opacity-100'"
        :aria-hidden="isEditing"
      >
        PigeonAgent 可能会犯错，请核查重要信息。
      </span>
      <span
        class="absolute inset-x-0 top-0 transition-opacity duration-200"
        :class="isEditing ? 'opacity-100' : 'opacity-0'"
        :aria-hidden="!isEditing"
      >
        保存后会开启新分支，原消息会保留
      </span>
    </p>
  </div>
</template>

<style scoped>
.edit-bar-enter-active,
.edit-bar-leave-active,
.edit-attachments-enter-active,
.edit-attachments-leave-active {
  display: grid;
  grid-template-rows: 1fr;
  overflow: hidden;
  transition:
    grid-template-rows 220ms cubic-bezier(0.22, 1, 0.36, 1),
    opacity 160ms ease;
}

.edit-bar-enter-from,
.edit-bar-leave-to,
.edit-attachments-enter-from,
.edit-attachments-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.edit-bar > div,
.edit-attachments > div {
  min-height: 0;
  overflow: hidden;
}

.edit-height {
  transition: height 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

@media (prefers-reduced-motion: reduce) {
  .edit-bar-enter-active,
  .edit-bar-leave-active,
  .edit-attachments-enter-active,
  .edit-attachments-leave-active,
  .edit-height {
    transition: none;
  }
}
</style>
