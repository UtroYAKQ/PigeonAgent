<script setup lang="ts">
import { ChevronLeft, ChevronRight } from "lucide-vue-next";
import { computed, watch } from "vue";
import type { Component } from "vue";

import FieldView from "./FieldView.vue";
import SchemaFields from "./SchemaFields.vue";
import { pendingPayload, usePendingBatch } from "../composables/usePendingBatch";
import { headlineOf } from "../render/infer";
import { readQuestions, type AskQuestion } from "../tools/askResult";
import { resolveHandler } from "../tools";
import type { ToolHandler } from "../tools";
import type { InterruptView } from "../types";

const props = defineProps<{ interrupts: InterruptView[] }>();

const emit = defineEmits<{
  (
    event: "submit",
    payload: {
      interruptId: string;
      approvals: Record<string, boolean>;
      calls: Record<string, unknown>;
    },
  ): void;
}>();

/** 批次状态住在 composable 里：面板重挂载、提交失败都不会丢答案。 */
const pending = usePendingBatch();

/**
 * 审批、回填、提问是三种不同的事，长相也不同，但它们绝不并列：
 * 一次只露一张卡，这张关掉下一张才弹出来。批次仍然是整体——
 * resume 必须一次交齐，不然后端 422。
 */
type Group = { interruptId: string; items: InterruptView[] };

const groups = computed<Group[]>(() => {
  const byBatch = new Map<string, InterruptView[]>();
  for (const item of props.interrupts) {
    const list = byBatch.get(item.interrupt_id);
    if (list) list.push(item);
    else byBatch.set(item.interrupt_id, [item]);
  }
  // 批次内的卡片按模型请求的先后（tool call 流里的顺序）排队
  return [...byBatch.entries()].map(([interruptId, items]) => ({ interruptId, items }));
});

function handlerOf(item: InterruptView): ToolHandler {
  return resolveHandler(item.name);
}

/** 答题区只有两种长相：工具自带组件，或按 schema 生成的表单。 */
function formOf(item: InterruptView): Component {
  const handler = handlerOf(item);
  return handler.execute === "manual" ? (handler.form ?? SchemaFields) : SchemaFields;
}

function callValue(item: InterruptView): unknown {
  return pending.valueOf(item.tool_call_id);
}

function isManualCall(item: InterruptView): boolean {
  return item.kind === "call" && handlerOf(item).execute === "manual";
}

/** 这个工具自带答题组件：交卷时机也由组件自己的按钮决定。 */
function hasCustomForm(item: InterruptView): boolean {
  const handler = handlerOf(item);
  return handler.execute === "manual" && !!handler.form;
}

/** 参数就是卡片内容的两种情况不再回显：auto 项已渲染过，自带答题组件的项由表单表达。 */
function showsArgs(item: InterruptView): boolean {
  return handlerOf(item).execute === "manual" && !hasCustomForm(item);
}

/** 每张提问卡的当前题号也住在批次状态里；翻页控件在面板的标题行上。 */
function askQuestionsOf(item: InterruptView): AskQuestion[] {
  return hasCustomForm(item) ? readQuestions(item.argsParsed ?? null) : [];
}

function askPageOf(item: InterruptView): number {
  const questions = askQuestionsOf(item);
  const page = pending.pageOf(item.tool_call_id);
  return Math.min(Math.max(page, 0), Math.max(questions.length - 1, 0));
}

function askEntryOf(item: InterruptView): AskQuestion | null {
  return askQuestionsOf(item)[askPageOf(item)] ?? null;
}

function setAskPage(item: InterruptView, index: number): void {
  const questions = askQuestionsOf(item);
  if (questions.length === 0) return;
  pending.setPage(item.tool_call_id, Math.min(Math.max(index, 0), questions.length - 1));
}

/** 只有带 questions 的自定义表单才吃 page/navigate，别把属性撒给别的表单。 */
function askBindings(item: InterruptView): Record<string, unknown> {
  if (askQuestionsOf(item).length === 0) return {};
  return { page: askPageOf(item), onNavigate: (index: number) => setAskPage(item, index) };
}

/** 人工 call 的内容够不够：决定「确定」能不能点（审批卡用不到，按钮始终可用）。 */
function filled(item: InterruptView): boolean {
  const handler = handlerOf(item);
  if (handler.execute === "auto") return callValue(item) !== undefined;
  return handler.isReady(callValue(item), pendingPayload(item));
}

/** auto 项自己就收掉了，人不欠它一次点击。 */
function settled(item: InterruptView): boolean {
  if (item.kind === "call" && handlerOf(item).execute === "auto") return filled(item);
  return pending.isSettled(item.tool_call_id);
}

function currentItem(group: Group): InterruptView | null {
  const open = group.items.find((item) => !settled(item));
  if (open) return open;
  // 全收掉了但批次还在（正在提交）：留着最后一张卡，别让浮层突然空掉
  return pending.submittingOf(group.interruptId)
    ? (group.items[group.items.length - 1] ?? null)
    : null;
}

/** 一批只出一张卡：每个批次当前露面的那一项。 */
type Card = { group: Group; item: InterruptView };

const cards = computed<Card[]>(() =>
  groups.value.flatMap<Card>((group) => {
    const item = currentItem(group);
    return item ? [{ group, item }] : [];
  }),
);

function submit(group: Group): void {
  if (group.items.some((item) => !settled(item))) return;
  if (!pending.beginSubmit(group.interruptId)) return;
  const approvalsPayload: Record<string, boolean> = {};
  const callsPayload: Record<string, unknown> = {};
  for (const item of group.items) {
    if (item.kind === "approval") {
      approvalsPayload[item.tool_call_id] = pending.approvalOf(item.tool_call_id) === true;
    } else {
      const handler = handlerOf(item);
      callsPayload[item.tool_call_id] =
        handler.execute === "auto"
          ? callValue(item)
          : handler.toResult(callValue(item), pendingPayload(item));
    }
  }
  emit("submit", {
    interruptId: group.interruptId,
    approvals: approvalsPayload,
    calls: callsPayload,
  });
}

/** 收掉这张卡；批次里没有别的卡了就交。 */
function close(item: InterruptView, group: Group): void {
  pending.settle(item.tool_call_id);
  submit(group);
}

function decide(item: InterruptView, group: Group, approved: boolean): void {
  pending.setApproval(item.tool_call_id, approved);
  close(item, group);
}

// 批次挂上就初始化：审批留空等人，auto 工具直接执行，manual 工具等表单
watch(
  () => props.interrupts,
  (items) => {
    pending.init(items);
    for (const group of groups.value) {
      // 全是 auto 的批次不用人动手，直接交
      if (group.items.every(settled)) submit(group);
    }
  },
  { immediate: true },
);

/** 卡标题：审批说清是谁要动手，调用点名工具；提问卡由表单画自己的题面。 */
function titleOf(item: InterruptView): string {
  if (item.kind === "approval") return `${item.name} 想要执行一个操作`;
  return `调用 ${item.name}`;
}

/** 审批要执行的具体动作；工具名本身就是句子时不再重复一行。 */
function actionOf(item: InterruptView): string {
  if (item.kind !== "approval") return "";
  const sentence = headlineOf(item.name, item.argsParsed ?? {});
  return sentence === item.name ? "" : sentence;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

/**
 * 面板只回显人工项的参数；auto 项的参数就是它已经渲染掉的载荷。
 * 动作句里已经说过的短值不再逐行重复（长的正文照常展示）。
 */
function argsOf(item: InterruptView): Record<string, unknown> {
  if (!showsArgs(item)) return {};
  const args = item.argsParsed ?? {};
  if (item.kind !== "approval") return args;
  const sentence = actionOf(item);
  return Object.fromEntries(
    Object.entries(args).filter(([, value]) => {
      const text = valueText(value);
      return text.length > 80 || !sentence.includes(text);
    }),
  );
}

function hasArgs(item: InterruptView): boolean {
  return Object.keys(argsOf(item)).length > 0;
}
</script>

<template>
  <section class="rise flex max-h-[62vh] w-full max-w-[var(--measure)] flex-col">
    <div class="min-h-0 flex-1 space-y-2.5 overflow-y-auto">
      <article
        v-for="card in cards"
        :key="card.item.tool_call_id"
        :class="[
          'rise rounded-surface border border-hair bg-surface px-4 pb-3 pt-3',
          pending.submittingOf(card.item.interrupt_id) ? 'pointer-events-none opacity-60' : '',
        ]"
      >
        <!-- 标题 / 内容 / 确认按钮；提问卡的题面、可多选和翻页也归面板管 -->
        <template v-if="hasCustomForm(card.item)">
          <div v-if="askEntryOf(card.item)" class="flex items-baseline gap-2">
            <h3 class="min-w-0 flex-1 text-body leading-6 font-medium text-ink">
              {{ askEntryOf(card.item)?.question }}
            </h3>
            <span v-if="askEntryOf(card.item)?.multi" class="shrink-0 text-micro text-faint">
              可多选
            </span>
            <div
              v-if="askQuestionsOf(card.item).length > 1"
              class="flex shrink-0 items-center gap-0.5 text-faint"
            >
              <button
                type="button"
                class="grid size-6 place-items-center rounded-md transition-colors hover:bg-hover hover:text-ink disabled:opacity-30"
                title="上一题"
                :disabled="askPageOf(card.item) === 0"
                @click="setAskPage(card.item, askPageOf(card.item) - 1)"
              >
                <ChevronLeft :size="14" />
              </button>
              <span class="num px-0.5 text-micro">
                {{ askPageOf(card.item) + 1 }}/{{ askQuestionsOf(card.item).length }}
              </span>
              <button
                type="button"
                class="grid size-6 place-items-center rounded-md transition-colors hover:bg-hover hover:text-ink disabled:opacity-30"
                title="下一题"
                :disabled="askPageOf(card.item) === askQuestionsOf(card.item).length - 1"
                @click="setAskPage(card.item, askPageOf(card.item) + 1)"
              >
                <ChevronRight :size="14" />
              </button>
            </div>
          </div>
        </template>
        <template v-else>
          <h3 class="text-body leading-6 font-medium text-ink">
            {{ titleOf(card.item) }}
          </h3>
          <p v-if="actionOf(card.item)" class="mt-0.5 text-ui leading-5 text-muted">
            {{ actionOf(card.item) }}
          </p>
        </template>

        <FieldView
          v-if="hasArgs(card.item)"
          :tool="card.item.name"
          :values="argsOf(card.item)"
        />
        <pre
          v-else-if="!card.item.argsParsed && showsArgs(card.item) && card.item.args"
          class="mt-2 max-h-24 overflow-auto rounded-control bg-inset px-2.5 py-1.5 font-mono text-micro whitespace-pre-wrap text-faint"
          >{{ card.item.args }}</pre
        >

        <template v-if="card.item.kind === 'call'">
          <p v-if="handlerOf(card.item).execute === 'auto'" class="mt-1 text-meta text-faint">
            已在浏览器里执行完，结果会自动回填。
          </p>
          <component
            v-else
            :is="formOf(card.item)"
            :model-value="pending.valueOf(card.item.tool_call_id)"
            :parameters="handlerOf(card.item).parameters"
            :item="pendingPayload(card.item)"
            v-bind="askBindings(card.item)"
            @update:model-value="pending.setValue(card.item.tool_call_id, $event)"
            @commit="close(card.item, card.group)"
          />
        </template>

        <footer
          v-if="card.item.kind === 'approval' || isManualCall(card.item)"
          class="mt-2 flex items-center justify-end gap-1"
        >
          <template v-if="card.item.kind === 'approval'">
            <button
              type="button"
              class="btn-card"
              @click="decide(card.item, card.group, false)"
            >
              拒绝
            </button>
            <button
              type="button"
              class="btn-card btn-card-primary"
              @click="decide(card.item, card.group, true)"
            >
              允许
            </button>
          </template>
          <button
            v-else-if="!hasCustomForm(card.item)"
            type="button"
            :class="['btn-card', filled(card.item) ? 'btn-card-primary' : '']"
            :disabled="!filled(card.item)"
            @click="close(card.item, card.group)"
          >
            确定
          </button>
        </footer>
      </article>
    </div>
  </section>
</template>
