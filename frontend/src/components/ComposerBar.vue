<script setup lang="ts">
import { ArrowUp, FileText, Film, Paperclip, Pencil, Square, X } from "lucide-vue-next";
import { computed, nextTick, onMounted, ref, watch } from "vue";

import ModelPicker from "./ModelPicker.vue";
import { uploadFile } from "../lib/api";
import { errorMessage } from "../lib/errors";
import { pushToast } from "../lib/toast";
import type { LlmModel, OutgoingAttachment, OutgoingResource } from "../types";

const MAX_FILES = 10;
/** 图片/视频走后端 attachments（RunCreate 上限 5）；文档走 resources，不占这个名额。 */
const MAX_MEDIA = 5;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_BYTES = 25 * 1024 * 1024;

const props = defineProps<{
  modelValue: string;
  running: boolean;
  editing?: boolean;
  blocked?: boolean;
  blockedReason?: string;
  models: LlmModel[];
  modelId: number | null;
  modelDisabled?: boolean;
}>();

/** 带文件的两条通道：图片/视频走 attachments（只带 file_id），文档走 resources 引用。 */
const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "send", prompt: string, attachments: OutgoingAttachment[], resources: OutgoingResource[]): void;
  (event: "stop"): void;
  (event: "cancel-edit"): void;
  (event: "model-change", modelId: number): void;
  (event: "manage-models"): void;
}>();

const input = ref<HTMLTextAreaElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const focused = ref(false);
const dragging = ref(false);
const attachments = ref<OutgoingAttachment[]>([]);
const resources = ref<OutgoingResource[]>([]);
const uploading = ref(0);
const attachmentError = ref("");

const fileCount = computed(() => attachments.value.length + resources.value.length);
const busyFiles = computed(() => uploading.value > 0);
const canSubmit = computed(
  () =>
    !props.running &&
    !busyFiles.value &&
    (props.modelValue.trim().length > 0 || fileCount.value > 0) &&
    (!props.blocked || props.editing),
);
const hint = computed(() => {
  if (props.editing) return "Enter 保存并重发 · Esc 取消";
  if (props.running) return "正在生成，可以随时停止";
  if (props.blocked) return props.blockedReason ?? "先选择一个模型";
  if (busyFiles.value) return "文件上传中…";
  if (fileCount.value > 0) return `已添加 ${fileCount.value} 个文件`;
  return "Enter 发送 · Shift+Enter 换行";
});

/** 按 scrollHeight 撑高，配合 CSS 的 max-h-56 裁剪；field-sizing 不支持的浏览器也能长高。 */
async function resize() {
  await nextTick();
  const element = input.value;
  if (!element) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, 224)}px`;
}

function focus() {
  const element = input.value;
  if (!element) return;
  element.focus();
  element.setSelectionRange(element.value.length, element.value.length);
}

defineExpose({ focus });

onMounted(() => {
  void resize();
  input.value?.focus();
});

watch(() => props.modelValue, () => void resize());
watch(
  () => props.editing,
  (editing) => {
    if (!editing) return;
    revokePreviews(attachments.value);
    revokePreviews(resources.value);
    attachments.value = [];
    resources.value = [];
    attachmentError.value = "";
  },
);

function revokePreviews(items: { preview?: string }[]): void {
  for (const item of items) {
    if (item.preview?.startsWith("blob:")) URL.revokeObjectURL(item.preview);
  }
}

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

/** 先走 /files 上传；图片视频发 file_id（后端回放时按 key 取字节），文档作为资源引用。 */
async function importFile(file: File): Promise<OutgoingAttachment | OutgoingResource> {
  const record = await uploadFile(file);
  const mediaType = record.content_type || file.type || "application/octet-stream";
  if (mediaType.startsWith("image/") || mediaType.startsWith("video/")) {
    return {
      kind: mediaType.startsWith("image/") ? "image" : "video",
      name: record.name,
      media_type: mediaType,
      file_id: record.id,
      size: record.size,
      preview: URL.createObjectURL(file),
    };
  }
  return {
    storage_key: record.id,
    name: record.name,
    media_type: mediaType,
    size: record.size,
    preview: undefined,
  };
}

async function addFiles(files: FileList | File[]) {
  if (props.editing || props.running) return;
  attachmentError.value = "";
  let total = [...attachments.value, ...resources.value].reduce(
    (sum, item) => sum + item.size,
    0,
  );
  const nextAttachments: OutgoingAttachment[] = [];
  const nextResources: OutgoingResource[] = [];
  for (const file of [...files]) {
    if (fileCount.value + nextAttachments.length + nextResources.length >= MAX_FILES) {
      attachmentError.value = `最多上传 ${MAX_FILES} 个文件`;
      break;
    }
    if (
      (file.type.startsWith("image/") || file.type.startsWith("video/")) &&
      attachments.value.length + nextAttachments.length >= MAX_MEDIA
    ) {
      attachmentError.value = `最多添加 ${MAX_MEDIA} 个图片/视频`;
      continue;
    }
    if (file.size > MAX_FILE_BYTES) {
      attachmentError.value = `${file.name} 超过 10 MB`;
      continue;
    }
    if (total + file.size > MAX_TOTAL_BYTES) {
      attachmentError.value = "附件总大小超过 25 MB";
      break;
    }
    try {
      uploading.value += 1;
      const imported = await importFile(file);
      total += file.size;
      if ("storage_key" in imported) nextResources.push(imported);
      else nextAttachments.push(imported);
    } catch (cause) {
      pushToast(`${file.name} 上传失败：${errorMessage(cause)}`);
    } finally {
      uploading.value -= 1;
    }
  }
  if (nextAttachments.length > 0)
    attachments.value = [...attachments.value, ...nextAttachments];
  if (nextResources.length > 0) resources.value = [...resources.value, ...nextResources];
}

function onFileInput(event: Event) {
  const element = event.target as HTMLInputElement;
  if (element.files) void addFiles(element.files);
  element.value = "";
}

function onDrop(event: DragEvent) {
  dragging.value = false;
  if (event.dataTransfer?.files.length) void addFiles(event.dataTransfer.files);
}

function onPaste(event: ClipboardEvent) {
  const files = event.clipboardData?.files;
  if (!files?.length) return;
  event.preventDefault();
  void addFiles(files);
}

function removeAttachment(kind: "attachment" | "resource", index: number) {
  if (kind === "resource") {
    revokePreviews(resources.value.slice(index, index + 1));
    resources.value = resources.value.filter((_, position) => position !== index);
    return;
  }
  revokePreviews(attachments.value.slice(index, index + 1));
  attachments.value = attachments.value.filter((_, position) => position !== index);
}

function submit() {
  const prompt = props.modelValue.trim();
  if (!canSubmit.value) return;
  emit("send", prompt, [...attachments.value], [...resources.value]);
  emit("update:modelValue", "");
  // 图片/视频的 blob 预览还被乐观气泡引用着，等轮次刷新后再随之失效，不在这里回收
  revokePreviews(resources.value);
  attachments.value = [];
  resources.value = [];
  attachmentError.value = "";
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && props.editing) {
    event.preventDefault();
    emit("cancel-edit");
    return;
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <div class="px-4 pb-3">
    <div
      class="mx-auto w-full max-w-[var(--measure)]"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <div
        :class="[
          'rounded-float border bg-canvas transition-colors',
          dragging
            ? 'border-accent'
            : editing || focused
              ? 'border-accent/50'
              : 'border-hair',
          blocked && !running ? 'opacity-80' : '',
        ]"
      >
        <div
          v-if="editing"
          class="flex items-center gap-1.5 px-4 pt-2.5 text-meta text-muted"
        >
          <Pencil :size="12" :stroke-width="1.7" />
          正在编辑消息
          <button
            class="ml-auto rounded-full px-2 py-0.5 text-faint transition-colors hover:bg-hover hover:text-ink"
            @click="emit('cancel-edit')"
          >
            取消
          </button>
        </div>

        <div v-if="fileCount" class="flex flex-wrap gap-2 px-3 pt-3">
          <template v-for="(resource, index) in resources" :key="`r${resource.storage_key}`">
            <div
              class="flex items-center gap-2 rounded-control border border-hair bg-inset px-2 py-1.5"
            >
              <img
                v-if="resource.preview"
                :src="resource.preview"
                :alt="resource.name"
                class="size-8 rounded-control object-cover"
              />
              <div
                v-else
                class="grid size-8 place-items-center rounded-control bg-canvas text-muted"
              >
                <FileText :size="15" :stroke-width="1.7" />
              </div>
              <div class="min-w-0 max-w-44">
                <div class="truncate text-meta text-ink">{{ resource.name }}</div>
                <div class="text-micro text-faint">{{ formatBytes(resource.size) }}</div>
              </div>
              <button
                class="rounded-control p-1 text-faint transition-colors hover:bg-hover hover:text-warn"
                :aria-label="`移除 ${resource.name}`"
                @click="removeAttachment('resource', index)"
              >
                <X :size="12" />
              </button>
            </div>
          </template>
          <template v-for="(attachment, index) in attachments" :key="`a${attachment.name}:${index}`">
            <div
              class="flex items-center gap-2 rounded-control border border-hair bg-inset px-2 py-1.5"
            >
              <img
                v-if="attachment.kind === 'image'"
                :src="attachment.preview"
                :alt="attachment.name"
                class="size-8 rounded-control object-cover"
              />
              <div v-else class="grid size-8 place-items-center rounded-control bg-canvas text-muted">
                <Film v-if="attachment.kind === 'video'" :size="15" :stroke-width="1.7" />
                <FileText v-else :size="15" :stroke-width="1.7" />
              </div>
              <div class="min-w-0 max-w-44">
                <div class="truncate text-meta text-ink">{{ attachment.name }}</div>
                <div class="text-micro text-faint">{{ formatBytes(attachment.size) }}</div>
              </div>
              <button
                class="rounded-control p-1 text-faint transition-colors hover:bg-hover hover:text-warn"
                :aria-label="`移除 ${attachment.name}`"
                @click="removeAttachment('attachment', index)"
              >
                <X :size="12" />
              </button>
            </div>
          </template>
        </div>

        <p v-if="attachmentError" class="px-4 pb-1 pt-2 text-micro text-warn">
          {{ attachmentError }}
        </p>

        <textarea
          ref="input"
          rows="1"
          :value="modelValue"
          :placeholder="
            editing ? '修改后按 Enter 重发' : '有问题，尽管问'
          "
          :disabled="blocked && !running"
          :class="[
            'max-h-56 w-full resize-none bg-transparent px-4 pb-1 text-body leading-6 outline-none disabled:cursor-not-allowed',
            editing || fileCount > 0 ? 'pt-2' : 'pt-3.5',
          ]"
          @focus="focused = true"
          @blur="focused = false"
          @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
          @keydown="onKeydown"
          @paste="onPaste"
        />

        <div class="flex flex-wrap items-center gap-1 px-2.5 pb-2">
          <ModelPicker
            :models="models"
            :model-value="modelId"
            :disabled="modelDisabled"
            @select="emit('model-change', $event)"
            @manage="emit('manage-models')"
          />
          <button
            type="button"
            class="rounded-control p-1.5 text-faint transition-colors hover:bg-hover hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="running || blocked || editing"
            title="上传文件"
            @click="fileInput?.click()"
          >
            <Paperclip :size="15" :stroke-width="1.7" />
          </button>
          <span class="hidden min-w-0 truncate px-1.5 text-meta text-faint sm:inline">
            {{ hint }}
          </span>
          <button
            :class="[
              'ml-auto grid size-9 place-items-center rounded-full transition-colors',
              running || canSubmit
                ? 'bg-ink text-canvas hover:opacity-85'
                : 'bg-hover text-faint',
            ]"
            :disabled="!running && !canSubmit"
            :aria-label="running ? '停止' : editing ? '保存并重发' : '发送'"
            @click="running ? emit('stop') : submit()"
          >
            <Square v-if="running" :size="13" fill="currentColor" :stroke-width="0" />
            <ArrowUp v-else :size="18" :stroke-width="2" />
          </button>
        </div>

        <input
          ref="fileInput"
          type="file"
          multiple
          class="hidden"
          @change="onFileInput"
        />
      </div>
      <p class="pt-2 text-center text-micro text-faint">
        内容由 AI 生成，请核对关键结论
      </p>
    </div>
  </div>
</template>
