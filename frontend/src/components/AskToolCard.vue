<script setup lang="ts">
import { MessageCircleQuestion } from "lucide-vue-next";
import { computed, ref } from "vue";

import ToolCardShell from "./ToolCardShell.vue";
import { readAskResult, readQuestions, type AskEntry } from "../tools/askResult";
import { KIND_TILE } from "../render/toolKind";
import type { ToolItem } from "../types";

const props = defineProps<{ item: ToolItem }>();

const open = ref(false);

const questions = computed(() => readQuestions(props.item.argsParsed ?? null));
const result = computed(() => readAskResult(props.item.result?.content));
const pending = computed(() => props.item.interrupt?.status === "pending");
const denied = computed(() => props.item.interrupt?.status === "denied");

interface Row {
  question: string;
  answer: string[];
  note: string;
  skipped: boolean;
}

/** 题目以参数为准，答案按顺序贴回去；老会话只有结果没有 questions 也能显示。 */
const rows = computed<Row[]>(() => {
  const source = questions.value.length
    ? questions.value.map((entry) => entry.question)
    : result.value.entries.map((entry) => entry.question);
  return source.map((question, index): Row => {
    const entry: AskEntry | undefined = result.value.entries[index];
    return {
      question,
      answer: entry?.answer ?? [],
      note: entry?.note ?? "",
      skipped: entry?.skipped === true,
    };
  });
});

/** 没答、被拒、整批跳过时只有一条状态行，不逐题重复。 */
const single = computed(
  () => pending.value || denied.value || result.value.skipped || rows.value.length === 0,
);

const statusText = computed(() => {
  if (pending.value) return "等你在下方回答";
  if (denied.value) return "已拒绝";
  return "已跳过";
});
const statusClass = computed(() => {
  if (pending.value) return "text-accent";
  if (denied.value) return "text-warn";
  return "text-faint";
});

function answerText(row: Row): string {
  if (row.skipped) return "已跳过";
  if (row.answer.length > 0) return row.answer.join("、");
  return row.note || "—";
}

function answerClass(row: Row): string {
  if (row.skipped) return "text-faint";
  return row.answer.length > 0 ? "text-ink font-medium" : "text-ink";
}

const onlyQuestion = computed(() => rows.value.length === 1 ? questions.value[0] : null);
const optionMeta = computed(() => {
  const entry = onlyQuestion.value;
  if (!entry) return "";
  const parts: string[] = [];
  if (entry.options.length) parts.push(`${entry.options.length} 个选项`);
  parts.push(entry.multi ? "可多选" : "单选");
  return parts.join(" · ");
});

/** 收起时行首说状态，后面跟第一题的题干。 */
const collapsedLabel = computed(() => {
  if (pending.value) return "等你回答";
  if (denied.value) return "已拒绝";
  if (rows.value.every((row) => row.skipped)) return "已跳过";
  return "已回答";
});
const collapsedClass = computed(() =>
  pending.value || denied.value ? "text-ink" : "",
);
</script>

<template>
  <ToolCardShell
    :tone="KIND_TILE.ask"
    :expanded="open"
    :label="collapsedLabel"
    :label-class="collapsedClass"
    :summary="rows[0]?.question ?? ''"
    summary-class="text-ink"
    @toggle="open = !open"
  >
    <template #icon>
      <MessageCircleQuestion :size="12" :stroke-width="1.8" />
    </template>

    <dl class="grid grid-cols-[18px_minmax(0,1fr)] gap-x-3 gap-y-2">
        <template v-if="!single">
          <template v-for="(row, index) in rows" :key="index">
            <dt class="pt-[3px] text-micro text-faint">问</dt>
            <dd class="text-ui leading-5 text-muted">{{ row.question }}</dd>

            <dt class="pt-[3px] text-micro text-faint">答</dt>
            <dd :class="['text-ui leading-5', answerClass(row)]">{{ answerText(row) }}</dd>

            <template v-if="row.note && row.answer.length > 0">
              <dt class="pt-[3px] text-micro text-faint">注</dt>
              <dd class="text-meta leading-5 text-muted">{{ row.note }}</dd>
            </template>
          </template>
        </template>

        <template v-else>
          <template v-for="(row, index) in rows" :key="`q-${index}`">
            <dt class="pt-[3px] text-micro text-faint">问</dt>
            <dd class="flex items-baseline gap-2.5 text-ui leading-5 text-muted">
              <span class="min-w-0">{{ row.question }}</span>
              <span v-if="index === 0 && optionMeta" class="num shrink-0 text-micro text-faint">
                {{ optionMeta }}
              </span>
            </dd>
          </template>
          <dt class="pt-[3px] text-micro text-faint">答</dt>
          <dd :class="['text-ui leading-5', statusClass]">{{ statusText }}</dd>
        </template>
      </dl>
  </ToolCardShell>
</template>
