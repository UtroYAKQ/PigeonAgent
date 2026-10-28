<script setup lang="ts">
import {
  ArrowLeftRight,
  Brain,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileText,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import FileChip from "./FileChip.vue";
import MarkdownText from "./MarkdownText.vue";
import FieldView from "./FieldView.vue";
import ToolCardShell from "./ToolCardShell.vue";
import { displayValue, headlineOf } from "../render/infer";
import { KIND_TILE, kindOf } from "../render/toolKind";
import { findHandler, type ToolPayload } from "../tools";
import { authedFetch } from "../lib/auth";
import type { Item } from "../types";

const props = defineProps<{ item: Item; caret?: boolean }>();

const open = ref(false);

// 落库的图片/视频只存 file_id：渲染时拉 blob 转 objectURL，同一文件只拉一次
const mediaBlobs = new Map<string, string>();
const mediaFailed = new Set<string>();
const mediaUrl = ref("");

const mediaFileId = computed(() => {
  if (props.item.type === "image" || props.item.type === "video") {
    if (props.item.url) return null;
    return props.item.fileId ?? null;
  }
  return null;
});

watch(
  mediaFileId,
  async (fileId) => {
    mediaUrl.value = "";
    if (!fileId) return;
    const cached = mediaBlobs.get(fileId);
    if (cached) {
      mediaUrl.value = cached;
      return;
    }
    if (mediaFailed.has(fileId)) return;
    try {
      const res = await authedFetch(`/files/${fileId}/content`);
      if (!res.ok) throw new Error(`fetch failed: ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      mediaBlobs.set(fileId, url);
      if (mediaFileId.value === fileId) mediaUrl.value = url;
    } catch {
      mediaFailed.add(fileId);
    }
  },
  { immediate: true },
);

const TOOL_LABEL: Record<string, string> = {
  streaming: "正在调用",
  ready: "等待结果",
  done: "已调用",
  error: "调用失败",
  interrupted: "已中断",
};

const asText = computed(() => (props.item.type === "text" ? props.item : null));
const asImage = computed(() => (props.item.type === "image" ? props.item : null));
const asVideo = computed(() => (props.item.type === "video" ? props.item : null));
const asFile = computed(() => (props.item.type === "file" ? props.item : null));
const asResource = computed(() => (props.item.type === "resource" ? props.item : null));
const asThinking = computed(() => (props.item.type === "thinking" ? props.item : null));
const asTool = computed(() => (props.item.type === "tool" ? props.item : null));
const asError = computed(() => (props.item.type === "error" ? props.item : null));
const asCustom = computed(() => (props.item.type === "custom" ? props.item : null));
// 卡片按 renderer + version 匹配；不认识的形状自动退回 JSON 展示
const customVersion = computed(() => (asCustom.value ? `v${asCustom.value.version ?? 1}` : ""));

const thinkingOpen = computed(
  () => open.value || asThinking.value?.status === "streaming",
);
const toolFailed = computed(() => asTool.value?.status === "error");
const toolLabel = computed(() =>
  asTool.value
    ? (TOOL_LABEL[toolFailed.value ? "error" : asTool.value.status] ?? asTool.value.status)
    : "",
);
/** 工具卡的类别标记：颜色只跟类别走（审批=警示红、调用=回填绿、普通=中性），状态交给文字。 */
const toolKind = computed(() => kindOf(asTool.value?.interrupt?.kind));
/** 折叠行说「发生了什么」而不是工具名；没有模板时退回工具名本身。 */
const toolTitle = computed(() => {
  const tool = asTool.value;
  if (!tool) return "";
  return headlineOf(tool.name, tool.argsParsed ?? {});
});
const toolTitleIsName = computed(() => toolTitle.value === asTool.value?.name);

/** 工具自己给了行内文案就当句子排，否则保持代码块。 */
const toolResult = computed<{ text: string; plain: boolean } | null>(() => {
  const tool = asTool.value;
  const content = tool?.result?.content;
  if (!tool || content == null || content === "") return null;
  const formatted = findHandler(tool.name)?.formatResult?.(content);
  return formatted ? { text: formatted, plain: true } : { text: content, plain: false };
});

const INTERRUPT_LABEL: Record<string, string> = {
  pending: "等待确认",
  approved: "已允许",
  denied: "已拒绝",
  resolved: "已回填",
};

// 中断自己就是结论时不再叠加"已调用/等待结果"，否则一行里会出现两个状态
const OWN_LABEL: Record<string, boolean> = {
  pending: true,
  denied: true,
};

const interrupt = computed(() => asTool.value?.interrupt ?? null);
const interruptLabel = computed(() => {
  const value = interrupt.value;
  if (!value) return "";
  // Call 等的是外部结果，不是用户的确认动作
  if (value.kind === "call" && value.status === "pending") return "等待外部结果";
  return INTERRUPT_LABEL[value.status] ?? value.status;
});
const showsOwnLabel = computed(
  () => !!interrupt.value && OWN_LABEL[interrupt.value.status] === true,
);
const toolHeadline = computed(() => (showsOwnLabel.value ? interruptLabel.value : toolLabel.value));

/** 工具自己带了卡片就用它的，没有才走下面的通用行。 */
const toolCard = computed(() => (asTool.value ? (findHandler(asTool.value.name)?.card ?? null) : null));

/** 前端工具的结果开在右侧面板里，历史卡片要能把它再打开。 */
const reopen = computed(() => {
  const tool = asTool.value;
  if (!tool) return null;
  const handler = findHandler(tool.name);
  if (!handler || handler.execute !== "auto" || !handler.reopen) return null;
  const payload: ToolPayload = {
    key: tool.toolCallId,
    name: tool.name,
    argsParsed: tool.argsParsed,
  };
  return {
    label: handler.reopenLabel ?? "打开",
    run: () => handler.reopen?.(payload),
  };
});

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

const customRecord = computed<Record<string, unknown> | null>(() => {
  const value = asCustom.value?.value;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
});
const customTitle = computed(() => {
  const title = customRecord.value?.title;
  return typeof title === "string" ? title : "";
});
const customText = computed(() => {
  const value = asCustom.value?.value;
  if (typeof value === "string") return value;
  const text = customRecord.value?.message ?? customRecord.value?.text;
  return typeof text === "string" ? text : "";
});
const customRows = computed<unknown[][] | null>(() => {
  const rows = customRecord.value?.rows;
  if (!Array.isArray(rows)) return null;
  const normalized = rows.filter((row): row is unknown[] => Array.isArray(row));
  return normalized.length > 0 ? normalized : null;
});
const customRaw = computed(() =>
  customTitle.value || customText.value || customRows.value ? "" : displayValue(asCustom.value?.value),
);
const rowOk = (value: unknown): boolean =>
  typeof value === "string" && (value.includes("通过") || value.includes("完成") || value.startsWith("已"));
</script>

<template>
  <MarkdownText
    v-if="asText && asText.role !== 'user' && asText.text"
    :text="asText.text"
    :caret="caret"
  />
  <p v-else-if="asText && asText.role === 'user' && asText.text" class="whitespace-pre-wrap">
    {{ asText.text }}
  </p>

  <img
    v-else-if="asImage && (asImage.url || mediaFileId)"
    :src="asImage.url || mediaUrl"
    :alt="asImage.alt ?? '图片'"
    class="max-h-80 max-w-full rounded-control object-contain"
  />
  <video
    v-else-if="asVideo && (asVideo.url || mediaFileId)"
    :src="asVideo.url || mediaUrl"
    :aria-label="asVideo.alt ?? '视频'"
    class="max-h-80 max-w-full rounded-control"
    controls
  />

  <div
    v-else-if="asFile"
    class="flex max-w-full items-center gap-2 rounded-surface border border-hair bg-surface px-3 py-2 text-ui"
  >
    <FileText :size="16" :stroke-width="1.7" class="shrink-0 text-muted" />
    <span class="min-w-0 truncate text-ink">{{ asFile.name }}</span>
    <span class="num ml-auto shrink-0 text-micro text-faint">{{ formatBytes(asFile.size) }}</span>
  </div>

  <!-- 文件资源：点击带上 Authorization 拉取 blob 再走浏览器下载 -->
  <FileChip
    v-else-if="asResource"
    :storage-key="asResource.storageKey"
    :name="asResource.name"
    :size="asResource.size"
  />

  <div v-else-if="asThinking" class="text-ui text-muted">
    <button
      class="flex items-center gap-1.5 py-0.5 transition-colors hover:text-ink"
      @click="open = !open"
    >
      <Brain :size="14" :stroke-width="1.7" />
      <span :class="asThinking.status === 'streaming' ? 'thinking-shimmer' : ''">
        {{
          asThinking.status === "streaming"
            ? "思考中"
            : open
              ? "收起思考过程"
              : "查看思考过程"
        }}
      </span>
      <ChevronDown
        :size="14"
        :class="['transition-transform', thinkingOpen ? 'rotate-180' : '']"
      />
    </button>
    <p
      v-if="thinkingOpen"
      class="mt-1 border-l border-hair pl-3 whitespace-pre-wrap text-muted"
    >
      {{ asThinking.text }}
    </p>
  </div>

  <!-- 工具自带卡片时不走下面的通用行；asTool 与 asText 互斥，所以这里另起一条链 -->
  <component
    :is="toolCard"
    v-if="asTool && toolCard"
    :item="asTool"
    @open="reopen?.run()"
  />

  <ToolCardShell
    v-else-if="asTool"
    :tone="KIND_TILE[toolKind]"
    :expanded="open"
    :label="toolHeadline"
    :label-class="[
      asTool.status === 'streaming' ? 'thinking-shimmer' : '',
      toolFailed ? 'text-warn' : showsOwnLabel ? 'text-ink' : '',
    ].join(' ')"
    :summary="toolTitle"
    :summary-class="asTool.status === 'interrupted' ? 'text-faint' : 'text-ink'"
    :summary-mono="toolTitleIsName"
    :summary-title="asTool.name"
    @toggle="open = !open"
  >
    <template #icon>
      <ShieldCheck v-if="toolKind === 'approval'" :size="12" :stroke-width="1.8" />
      <ArrowLeftRight v-else-if="toolKind === 'call'" :size="12" :stroke-width="1.8" />
      <Wrench v-else :size="12" :stroke-width="1.8" />
    </template>
    <template v-if="reopen" #trailing>
      <button
        class="rounded-full border border-hair px-2 py-0.5 text-micro text-muted transition-colors hover:bg-hover hover:text-ink"
        @click.stop="reopen.run()"
      >
        {{ reopen.label }}
      </button>
    </template>

    <div class="space-y-2.5">
      <FieldView v-if="asTool.argsParsed" :tool="asTool.name" :values="asTool.argsParsed" />
      <pre v-else-if="asTool.args" class="code-box text-muted">{{ asTool.args }}</pre>
      <div v-if="asTool.result">
        <div v-if="asTool.result.media?.length" class="mb-1.5 flex flex-wrap gap-1.5">
          <template v-for="(media, index) in asTool.result.media" :key="index">
            <img
              v-if="media.type === 'image'"
              :src="media.url"
              :alt="asTool.name"
              class="max-h-40 max-w-[240px] rounded-control border border-hair object-contain"
            />
            <video
              v-else
              :src="media.url"
              class="max-h-40 max-w-[240px] rounded-control border border-hair"
              controls
            />
          </template>
        </div>
        <div v-if="toolResult" class="flex max-h-72 items-baseline gap-2 overflow-y-auto">
          <span class="shrink-0 text-micro text-faint">
            {{ asTool.result.status === "error" ? "错误" : "结果" }}
          </span>
          <p
            :class="[
              'min-w-0 flex-1 whitespace-pre-wrap break-words text-meta leading-5',
              toolResult.plain ? 'text-muted' : 'font-mono',
              asTool.result.status === 'error' ? 'text-warn' : 'text-muted',
            ]"
          >
            <span v-if="toolResult.plain" class="text-ok">✓</span>
            {{ toolResult.text }}
          </p>
        </div>
        <p
          v-else-if="!asTool.result.media?.length && !asTool.result.files?.length"
          class="text-micro text-faint"
        >
          (empty)
        </p>
      </div>
    </div>
  </ToolCardShell>

  <div
    v-if="asError"
    class="flex items-start gap-2 rounded-surface border border-warn/30 bg-warn/5 px-3 py-2.5 text-ui text-warn"
  >
    <CircleAlert :size="15" class="mt-0.5 shrink-0" />
    <div>
      <div class="font-medium">{{ asError.code ?? "run_failed" }}</div>
      <div class="text-muted">{{ asError.message }}</div>
    </div>
  </div>

  <div v-else-if="asCustom" class="rounded-surface border border-hair bg-surface px-3.5 py-3">
    <div class="flex items-center gap-2 text-meta text-faint">
      <Sparkles :size="13" :stroke-width="1.7" class="text-accent" />
      <span class="font-mono">{{ asCustom.name }}</span>
      <span class="ml-auto flex items-center gap-1.5">
        <span v-if="customVersion" class="font-mono text-micro text-faint">{{ customVersion }}</span>
        <span class="rounded-full bg-canvas px-2 py-0.5 text-micro tracking-wide">CARD</span>
      </span>
    </div>
    <h3 v-if="customTitle" class="mt-1.5 text-ui font-medium text-ink">{{ customTitle }}</h3>
    <div
      v-if="customRows"
      class="mt-2 overflow-hidden rounded-control border border-hair bg-canvas"
    >
      <div
        v-for="(row, index) in customRows"
        :key="index"
        class="flex items-center gap-3 border-b border-hair px-2.5 py-1.5 last:border-0"
      >
        <span class="min-w-0 flex-1 truncate text-meta text-muted">{{ row[0] }}</span>
        <span class="flex items-center gap-1 text-meta text-ink">
          <CheckCircle2 v-if="rowOk(row[1])" :size="12" class="text-ok" />
          {{ row[1] }}
        </span>
      </div>
    </div>
    <p v-else-if="customText" class="mt-1.5 whitespace-pre-wrap text-ui leading-6 text-ink">
      {{ customText }}
    </p>
    <pre v-else-if="customRaw" class="code-box mt-2 max-h-72 overflow-y-auto text-muted">{{ customRaw }}</pre>
  </div>

</template>
