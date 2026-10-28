<script setup lang="ts">
import { Ban, Check, ChevronLeft, ChevronRight, Copy, Pencil, RefreshCw } from "lucide-vue-next";
import { computed, ref } from "vue";

import FileChip from "./FileChip.vue";
import ItemBlock from "./ItemBlock.vue";
import { isPlanTool } from "../lib/plan";
import { copyText } from "../lib/clipboard";
import type { DisplayBlock, Item, ResultFile, TextItem } from "../types";

const props = defineProps<{
  block: DisplayBlock;
  running: boolean;
  isLast: boolean;
  editing?: boolean;
  pending?: boolean;
}>();

const emit = defineEmits<{
  (event: "regenerate", block: DisplayBlock): void;
  (event: "edit", block: DisplayBlock, text: string): void;
  (event: "branch", headRunId: string): void;
}>();

const copied = ref(false);

const streaming = computed(() => props.block.status === "streaming");
const caretFor = (item: Item) =>
  streaming.value && item.type === "text" && item.status === "streaming";
const answerText = computed(() =>
  props.block.items
    .filter((item): item is TextItem => item.type === "text" && item.role === "assistant")
    .map((item) => item.text)
    .join("\n")
    .trim(),
);
const hasAnswer = computed(() => answerText.value.length > 0);
/** 报错块的同一个动作改叫「重试」，避免出现两个语义重复的按钮。 */
const errored = computed(() => props.block.items.some((item) => item.type === "error"));
const promptText = computed(() =>
  props.block.items
    .filter((item): item is TextItem => item.type === "text" && item.role === "user")
    .map((item) => item.text)
    .join("\n"),
);
const hasAttachments = computed(() =>
  props.block.items.some(
    (item) =>
      item.type === "image" || item.type === "video" || item.type === "resource",
  ),
);
/** 清单工具是过程性的，正文里不占行：状态集中在输入框上方那个浮窗。 */
const visible = computed(() =>
  props.block.items.filter((item) => item.type !== "tool" || !isPlanTool(item.name)),
);
/** 工具发布的可下载文件提到消息级展示：折叠的工具卡里点不到，用户第一眼就要能下。 */
const blockFiles = computed<ResultFile[]>(() => {
  const seen = new Set<string>();
  for (const item of visible.value) {
    if (item.type === "resource") seen.add(item.storageKey);
  }
  const files: ResultFile[] = [];
  for (const item of visible.value) {
    if (item.type !== "tool" || !item.result?.files) continue;
    for (const file of item.result.files) {
      if (seen.has(file.storageKey)) continue;
      seen.add(file.storageKey);
      files.push(file);
    }
  }
  return files;
});

/** 分支导航：当前是第几个分支，点箭头切到相邻分支。 */
const branch = computed(() => props.block.branch ?? null);
const navDisabled = computed(() => props.running || streaming.value);

function step(direction: -1 | 1) {
  const nav = branch.value;
  if (!nav || navDisabled.value) return;
  const target = nav.leaves[nav.position - 1 + direction];
  if (target) emit("branch", target);
}

function startEdit() {
  if (props.running || hasAttachments.value || props.block.runIds.length === 0) return;
  emit("edit", props.block, promptText.value);
}

async function copy() {
  if (!(await copyText(answerText.value))) return;
  copied.value = true;
  window.setTimeout(() => (copied.value = false), 1400);
}
</script>

<template>
  <div v-if="block.role === 'user'" class="rise flex flex-col items-end gap-1.5">
    <div
      :class="[
        'max-w-[85%] rounded-float bg-inset px-4 py-2.5 text-body whitespace-pre-wrap',
        editing ? 'ring-2 ring-accent/15' : '',
      ]"
    >
      <ItemBlock v-for="item in visible" :key="item.id" :item="item" />
    </div>

    <div class="flex items-center gap-2">
      <div v-if="branch" class="num flex items-center gap-0.5 text-meta text-faint">
        <button
          class="rounded p-0.5 transition-colors hover:text-ink disabled:opacity-30"
          :disabled="navDisabled || branch.position <= 1"
          title="上一个版本"
          @click="step(-1)"
        >
          <ChevronLeft :size="13" />
        </button>
        <span>{{ branch.position }}/{{ branch.total }}</span>
        <button
          class="rounded p-0.5 transition-colors hover:text-ink disabled:opacity-30"
          :disabled="navDisabled || branch.position >= branch.total"
          title="下一个版本"
          @click="step(1)"
        >
          <ChevronRight :size="13" />
        </button>
      </div>
      <button
        v-if="!running && !pending && !isLast && !editing && !hasAttachments"
        class="flex items-center gap-1 text-meta text-faint transition-colors hover:text-ink"
        @click="startEdit"
      >
        <Pencil :size="12" />
        编辑
      </button>
      <span v-else-if="editing" class="flex items-center gap-1 text-meta text-muted">
        <Pencil :size="12" />
        编辑中
      </span>
    </div>
  </div>

  <div v-else class="rise flex flex-col gap-2.5">
    <p v-if="visible.length === 0 && streaming" class="text-ui text-faint">
      正在启动…
    </p>

    <ItemBlock
      v-for="item in visible"
      :key="item.id"
      :item="item"
      :caret="caretFor(item)"
    />

    <div v-if="blockFiles.length" class="flex flex-wrap gap-1.5">
      <FileChip
        v-for="file in blockFiles"
        :key="file.storageKey"
        :storage-key="file.storageKey"
        :name="file.name"
        :size="file.size"
      />
    </div>

    <div v-if="!streaming" class="flex flex-wrap items-center gap-2 pt-0.5">
      <span
        v-if="block.interrupted"
        class="flex items-center gap-1 text-meta text-faint"
      >
        <Ban :size="12" :stroke-width="1.7" />
        已中断
      </span>
      <button
        v-if="(hasAnswer || errored) && !running && !pending && block.answerTo"
        class="flex w-fit items-center gap-1 text-meta text-faint transition-colors hover:text-ink"
        @click="emit('regenerate', block)"
      >
        <RefreshCw :size="12" />
        {{ errored ? "重试" : "重新生成" }}
      </button>
      <button
        v-if="hasAnswer"
        class="flex w-fit items-center gap-1 text-meta text-faint transition-colors hover:text-ink"
        @click="copy"
      >
        <Check v-if="copied" :size="12" />
        <Copy v-else :size="12" />
        {{ copied ? "已复制" : "复制" }}
      </button>
    </div>
  </div>
</template>
