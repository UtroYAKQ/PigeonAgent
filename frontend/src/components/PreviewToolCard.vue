<script lang="ts">
/** 展开状态记在模块上：卡片重挂载（刷新、run 收口换块）后不该把正在看的代码收起来。 */
const openCards = new Map<string, boolean>();

/** 只增不减会跟着整场会话涨，留最近的一批就够。 */
function rememberCard(id: string, open: boolean): void {
  openCards.set(id, open);
  if (openCards.size > 200) {
    const oldest = openCards.keys().next().value;
    if (oldest !== undefined) openCards.delete(oldest);
  }
}
</script>

<script setup lang="ts">
import { ChevronDown, Code, Maximize2 } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { codeHtml } from "../render/infer";
import { copyText } from "../lib/clipboard";
import { useSurfaces } from "../composables/useSurfaces";
import type { ToolItem } from "../types";

const props = defineProps<{ item: ToolItem }>();

const emit = defineEmits<{ (event: "open"): void }>();

const streaming = computed(() => props.item.status === "streaming");
const failed = computed(() => props.item.status === "error");

/** args 还没闭合时 JSON 解析不了，先把已经流出来的顶层字段抠出来，卡片才能边生成边长。 */
const fields = computed<Record<string, unknown>>(
  () => props.item.argsParsed ?? streamedFields(props.item.args),
);
const title = computed(() => String(fields.value.title ?? "网页预览"));
const html = computed(() => String(fields.value.html ?? ""));
const hasHtml = computed(() => html.value.trim() !== "");
const canOpen = computed(() => !streaming.value && !failed.value && hasHtml.value);
/** 有源码可看时，整行都是展开开关。 */
const canToggle = computed(() => hasHtml.value && !failed.value);

/**
 * 流式期间挂上的卡默认摊开，之后保持，除非人自己收起来。
 */
if (props.item.status === "streaming" && !openCards.has(props.item.toolCallId)) {
  rememberCard(props.item.toolCallId, true);
}
const showCode = ref(openCards.get(props.item.toolCallId) ?? false);

function toggleCode(): void {
  if (!canToggle.value) return;
  showCode.value = !showCode.value;
  rememberCard(props.item.toolCallId, showCode.value);
}

const copied = ref(false);

async function copy(): Promise<void> {
  if (!(await copyText(html.value))) return;
  copied.value = true;
  window.setTimeout(() => (copied.value = false), 1400);
}

/** 侧边那一页读源码，比在卡片里滚动舒服。 */
function expand(): void {
  useSurfaces().open({
    key: `code-${props.item.toolCallId}`,
    kind: "code",
    title: `${title.value} · 源码`,
    body: html.value,
    lang: "html",
  });
}

/** 高亮整段 HTML 不便宜：流式时限频到 ~8fps，收尾时立即对齐最终文本。 */
const shown = ref("");
let tick = 0;
watch(
  [html, streaming],
  () => {
    if (!streaming.value) {
      window.clearTimeout(tick);
      tick = 0;
      shown.value = html.value;
      return;
    }
    if (tick) return;
    tick = window.setTimeout(() => {
      tick = 0;
      shown.value = html.value;
    }, 120);
  },
  { immediate: true },
);
onBeforeUnmount(() => window.clearTimeout(tick));

/** highlight.js 出来的串已经转过义，可以直接 v-html。 */
const source = computed(() => codeHtml(shown.value.trim(), "html"));

function sizeOf(text: string): string {
  const bytes = new TextEncoder().encode(text).length;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

const meta = computed(() => {
  if (streaming.value) {
    return hasHtml.value ? `${sizeOf(html.value)} · 正在生成…` : "正在生成…";
  }
  if (failed.value) return "生成失败";
  if (!hasHtml.value) return "没有可预览的内容";
  return `HTML · ${sizeOf(html.value)}`;
});

function skip(raw: string, index: number, pattern: RegExp): number {
  while (index < raw.length && pattern.test(raw[index])) index += 1;
  return index;
}

/** 字符串值的结束位置（不含引号）；流到一半没有结束引号时返回 -1。 */
function stringEnd(raw: string, start: number): number {
  let index = start + 1;
  while (index < raw.length) {
    if (raw[index] === "\\") index += 2;
    else if (raw[index] === '"') return index + 1;
    else index += 1;
  }
  return -1;
}

/** 没闭合的字符串得自己解转义：JSON.parse 只吃完整字面量。 */
function unescapePartial(text: string): string {
  return text.replace(/\\(u[0-9a-fA-F]{0,4}|[\s\S])/g, (_match, seq: string) => {
    switch (seq[0]) {
      case "n":
        return "\n";
      case "t":
        return "\t";
      case "r":
        return "\r";
      case "b":
        return "\b";
      case "f":
        return "\f";
      case "u":
        return seq.length === 5 ? String.fromCharCode(parseInt(seq.slice(1), 16)) : "";
      default:
        return seq;
    }
  });
}

/** 只认顶层对象；嵌套的对象/数组在流式阶段没被这两个字段用到，遇到就停。 */
function streamedFields(raw: string): Record<string, unknown> {
  const fields: Record<string, unknown> = {};
  let index = raw.indexOf("{");
  if (index < 0) return fields;
  index += 1;
  while (index < raw.length) {
    index = skip(raw, index, /[\s,]/);
    if (raw[index] !== '"') break;
    const keyEnd = stringEnd(raw, index);
    if (keyEnd < 0) break;
    const key = JSON.parse(raw.slice(index, keyEnd)) as string;
    index = skip(raw, keyEnd, /\s/);
    if (raw[index] !== ":") break;
    index = skip(raw, index + 1, /\s/);
    if (raw[index] === '"') {
      const end = stringEnd(raw, index);
      if (end < 0) {
        fields[key] = unescapePartial(raw.slice(index + 1));
        break;
      }
      fields[key] = JSON.parse(raw.slice(index, end));
      index = end;
      continue;
    }
    const literal = /^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)(?=[\s,}]|$)/.exec(
      raw.slice(index),
    );
    if (!literal) break;
    fields[key] = JSON.parse(literal[0]);
    index += literal[0].length;
  }
  return fields;
}
</script>

<template>
  <div class="overflow-hidden rounded-surface border border-hair bg-surface">
    <div
      :class="['flex items-center gap-3 px-3 py-2.5', canToggle ? 'cursor-pointer select-none' : '']"
      @click="toggleCode"
    >
      <span
        :class="[
          'grid size-9 shrink-0 place-items-center rounded-control',
          canOpen ? 'bg-accent-soft text-accent' : 'bg-hover text-faint',
        ]"
      >
        <Code :size="16" :stroke-width="1.7" />
      </span>
      <div class="min-w-0 flex-1">
        <span :class="['block truncate text-ui', canOpen ? 'text-ink' : 'text-muted']">
          {{ title }}
        </span>
        <span
          :class="[
            'num block truncate text-micro',
            streaming ? 'thinking-shimmer' : 'text-faint',
          ]"
          >{{ meta }}</span
        >
      </div>
      <button
        v-if="canOpen"
        class="btn btn-ghost shrink-0 border border-hair"
        @click.stop="emit('open')"
      >
        打开预览
      </button>
      <ChevronDown
        v-if="canToggle"
        :size="14"
        :stroke-width="1.7"
        :class="['shrink-0 text-faint transition-transform', showCode ? 'rotate-180' : '']"
      />
    </div>

    <div v-if="showCode" class="code-frame rise mx-3 mb-3">
      <div class="code-bar">
        <span class="code-lang">html</span>
        <button
          type="button"
          class="code-btn code-expand"
          title="在侧边展开"
          aria-label="在侧边展开代码"
          @click="expand"
        >
          <Maximize2 :size="12" :stroke-width="1.7" />
        </button>
        <button type="button" class="code-btn code-copy" @click="copy">
          {{ copied ? "已复制" : "复制" }}
        </button>
      </div>
      <pre
        class="overflow-x-auto px-3 py-2 font-mono text-meta leading-relaxed whitespace-pre-wrap break-words text-muted"
        v-html="source"
      />
    </div>
  </div>
</template>
