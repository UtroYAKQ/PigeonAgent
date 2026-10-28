<script setup lang="ts">
import { Check, X } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

import {
  allAnswered,
  answered,
  readForm,
  readQuestions,
  type AskAnswer,
} from "../tools/askResult";
import type { ToolPayload } from "../tools";

const props = defineProps<{
  modelValue: unknown;
  item?: ToolPayload;
  parameters?: Record<string, unknown>;
  /** 当前题号由面板的标题行控制；表单只负责这一屏的答案。 */
  page?: number;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: unknown): void;
  /** 这一项已经答完，可以让整批试着提交了。 */
  (event: "commit"): void;
  /** 请求翻到第 index 题（面板改 page，表单只发意图）。 */
  (event: "navigate", index: number): void;
}>();

/** 题目来自参数，一次调用可以问 1-4 个；形状跑偏就退化成自由输入。 */
const questions = computed(() => readQuestions(props.item?.argsParsed ?? null));
const answers = computed<AskAnswer[]>(() => readForm(props.modelValue, questions.value.length));

const current = computed(() => {
  const last = Math.max(questions.value.length - 1, 0);
  return Math.min(Math.max(props.page ?? 0, 0), last);
});
const entry = computed(() => questions.value[current.value] ?? null);

function write(next: AskAnswer[]): void {
  emit("update:modelValue", { answers: next });
}

function patch(index: number, part: Partial<AskAnswer>): void {
  write(answers.value.map((answer, i) => (i === index ? { ...answer, ...part } : answer)));
}

function goTo(index: number): void {
  if (editing.value !== null) saveDraft(editing.value);
  emit("navigate", index);
}

/** 答完一题就翻到下一题没答的；全答完了就停在原处，让他自己点完成。 */
function advance(from: number): void {
  const open = (index: number) => index !== from && !answered(answers.value[index]);
  const next = questions.value.findIndex((_, index) => index > from && open(index));
  const wrap = questions.value.findIndex((_, index) => index < from && open(index));
  const target = next >= 0 ? next : wrap;
  if (target >= 0) void nextTick(() => goTo(target));
}

/** 点选项只记选择，单选也一样交卷给完成按钮——手滑还能改回来。 */
function pick(index: number, label: string, multi: boolean): void {
  const answer = answers.value[index];
  // 选了预设选项就等于放弃自定义答案，两个答案不能同时成立
  if (!multi) {
    patch(index, { selected: [label], note: "" });
    advance(index);
    return;
  }
  patch(index, {
    note: "",
    selected: answer.selected.includes(label)
      ? answer.selected.filter((picked) => picked !== label)
      : [...answer.selected, label],
  });
}

// 「我来描述。」是每题列表的最后一项，点开才就地换成输入框；一屏只有一题
const editing = ref<number | null>(null);
const noteInput = ref<HTMLInputElement | HTMLTextAreaElement | null>(null);
const draft = ref("");

function startEdit(index: number): void {
  editing.value = index;
  draft.value = answers.value[index]?.note ?? "";
  void nextTick(() => noteInput.value?.focus());
}

/** 空着保存就是清除：自定义答案必须能撤回。 */
function saveDraft(index: number): void {
  patch(index, { note: draft.value.trim() });
  editing.value = null;
}

function clearNote(index: number): void {
  patch(index, { note: "" });
  draft.value = "";
  editing.value = null;
}

/** 无选项的自由输入也用同一个清除入口。 */
function clearText(): void {
  draft.value = "";
  patch(current.value, { note: "" });
}

// 面板的翻页按钮直接改 page：切走前把正在编辑的草稿落下来
watch(
  () => props.page,
  () => {
    if (editing.value !== null) saveDraft(editing.value);
  },
);

function finish(): void {
  if (editing.value !== null) saveDraft(editing.value);
  emit("commit");
}

function skipAll(): void {
  write(answers.value.map((answer) => ({ ...answer, skipped: true })));
  emit("commit");
}

const ready = computed(() => allAnswered(answers.value));
</script>

<template>
  <div>
    <p v-if="questions.length === 0" class="text-meta text-faint">
      这次提问没带选项，直接写下你的回答就行。
    </p>

    <section v-if="entry" :key="current">
      <div v-if="entry.options.length === 0" class="relative">
        <textarea
          ref="noteInput"
          v-model="draft"
          rows="3"
          placeholder="写下你的回答"
          class="w-full resize-y rounded-lg border border-hair bg-canvas px-2.5 py-2 pr-9 text-ui leading-5 outline-none focus:border-ink/30"
          @blur="saveDraft(current)"
          @keydown.esc.prevent="editing = null"
        />
        <button
          v-if="draft || answers[current].note"
          type="button"
          class="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-md text-faint transition-colors hover:bg-hover hover:text-ink"
          title="清除回答"
          @click="clearText"
        >
          <X :size="14" />
        </button>
      </div>

      <div v-else class="-mx-2 mt-1">
        <button
          v-for="(option, optionIndex) in entry.options"
          :key="option.label"
          type="button"
          class="flex w-full gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
          @click="pick(current, option.label, entry.multi)"
        >
          <span
            :class="[
              'mt-[3px] grid size-3.5 shrink-0 place-items-center rounded border transition-colors',
              answers[current].selected.includes(option.label)
                ? 'border-ink bg-ink text-canvas'
                : 'border-faint/60 bg-canvas',
            ]"
          >
            <Check
              v-if="answers[current].selected.includes(option.label)"
              :size="10"
              :stroke-width="3"
            />
          </span>
          <span class="min-w-0">
            <span
              :class="[
                'block text-ui leading-5',
                answers[current].selected.includes(option.label) ? 'text-ink' : 'text-muted',
              ]"
            >
              {{ optionIndex + 1 }}. {{ option.label }}
            </span>
            <span
              v-if="option.description"
              class="block pl-5 text-meta leading-5 text-faint"
            >
              {{ option.description }}
            </span>
          </span>
        </button>

        <div v-if="editing === current" class="flex items-center gap-2 rounded-md bg-inset px-2 py-1.5">
          <button
            type="button"
            class="grid size-3.5 shrink-0 place-items-center rounded border border-ink bg-ink text-canvas"
            title="取消自定义填写"
            @click="clearNote(current)"
          >
            <Check :size="10" :stroke-width="3" />
          </button>
          <span class="num shrink-0 text-ui leading-5 text-faint">
            {{ entry.options.length + 1 }}.
          </span>
          <input
            ref="noteInput"
            v-model="draft"
            placeholder="写下你的回答"
            class="ask-inline-input min-w-0 flex-1 border-0 bg-transparent text-ui leading-5 text-ink outline-none placeholder:text-faint"
            @keydown.enter.prevent="saveDraft(current)"
            @keydown.esc.prevent="editing = null"
          />
          <button
            type="button"
            class="grid size-6 shrink-0 place-items-center rounded-md text-faint transition-colors hover:bg-hover hover:text-ink"
            title="取消自定义填写"
            @click="clearNote(current)"
          >
            <X :size="14" />
          </button>
        </div>
        <div
          v-else-if="answers[current].note"
          class="flex items-start gap-2 rounded-md px-2 py-1.5"
        >
          <button
            type="button"
            class="mt-[3px] grid size-3.5 shrink-0 place-items-center rounded border border-ink bg-ink text-canvas"
            title="取消自定义回答"
            @click="clearNote(current)"
          >
            <Check :size="10" :stroke-width="3" />
          </button>
          <span class="num shrink-0 text-ui leading-5 text-faint">
            {{ entry.options.length + 1 }}.
          </span>
          <button
            type="button"
            class="min-w-0 flex-1 text-left text-ui leading-5 break-words text-ink"
            @click="startEdit(current)"
          >
            {{ answers[current].note }}
          </button>
          <button
            type="button"
            class="grid size-6 shrink-0 place-items-center rounded-md text-faint transition-colors hover:bg-hover hover:text-ink"
            title="清除自定义回答"
            @click="clearNote(current)"
          >
            <X :size="14" />
          </button>
        </div>
        <button
          v-else
          type="button"
          class="flex w-full gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
          @click="startEdit(current)"
        >
          <span class="size-3.5 shrink-0" />
          <span class="text-ui leading-5 text-muted">
            {{ entry.options.length + 1 }}. 我来描述。
          </span>
        </button>
      </div>
    </section>

    <div class="mt-2.5 flex items-center justify-end gap-1">
      <button type="button" class="btn-card" @click="skipAll">跳过</button>
      <button
        type="button"
        :class="['btn-card', ready ? 'btn-card-primary' : '']"
        :disabled="!ready"
        @click="finish"
      >
        完成
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 行内编辑不需要输入框自己的焦点环，光标和行底色已经说明状态 */
.ask-inline-input:focus-visible {
  outline: none;
}
</style>
