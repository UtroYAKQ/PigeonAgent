<script setup lang="ts">
import { PanelLeft } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

import ApprovalPanel from "./ApprovalPanel.vue";
import ComposerBar from "./ComposerBar.vue";
import HomeWorkbench from "./HomeWorkbench.vue";
import MessageRow from "./MessageRow.vue";
import PlanDock from "./PlanDock.vue";
import { useThread } from "../composables/useThread";
import { usePendingBatch } from "../composables/usePendingBatch";
import { planOf } from "../lib/plan";
import type {
  DisplayBlock,
  LlmModel,
  OutgoingAttachment,
  OutgoingResource,
  Session,
  SessionGroup,
} from "../types";

const props = defineProps<{
  sessionId: string;
  sidebarOpen: boolean;
  models: LlmModel[];
  modelId: number | null;
  /** 主页工作台要展示分组和最近会话；会话列表由 App 统一持有。 */
  groups: SessionGroup[];
  sessions: Session[];
  /** 草稿页发来的第一条消息：会话是这时才建的，挂载后立刻发出去。 */
  initialMessage?: {
    input: string;
    attachments: OutgoingAttachment[];
    resources?: OutgoingResource[];
  } | null;
}>();

const emit = defineEmits<{
  (event: "toggle-sidebar"): void;
  (event: "open-session", sessionId: string): void;
  (event: "new-in-group", groupId: number): void;
  (event: "create-group", name: string): void;
  (event: "initial-consumed"): void;
  (event: "run-end"): void;
  (event: "session-gone"): void;
  (event: "open-settings"): void;
  (event: "model-change", modelId: number): void;
}>();

const selectedModel = ref<number | null>(props.modelId);
const draft = ref("");
const scroller = ref<HTMLElement | null>(null);
const composer = ref<InstanceType<typeof ComposerBar> | null>(null);
const editingBlock = ref<DisplayBlock | null>(null);
const draftBeforeEdit = ref("");
let pinned = true;
let userScrolled = false;

const thread = useThread(props.sessionId, selectedModel);
const pendingBatch = usePendingBatch();
const activeModels = computed(() => props.models.filter((model) => model.is_active));
const interrupts = thread.interrupts;
const pending = computed(() => interrupts.value.length > 0);
/** 后端说还有未决批次，但卡片不在当前分页里：只能拦住发送，让它去加载更早的消息。 */
const hiddenPending = computed(
  () => thread.pendingCount.value > 0 && !pending.value && !thread.running.value,
);
const canSend = computed(() => activeModels.value.length > 0 && selectedModel.value != null);
/** 本轮的清单浮窗：跑完就收，历史里的 plan 卡片留在消息流里。 */
const plan = computed(() =>
  thread.running.value || pending.value ? planOf(thread.blocks.value) : null,
);

watch(
  () => props.modelId,
  (value) => {
    if (value != null && value !== selectedModel.value) selectedModel.value = value;
  },
);

watch(selectedModel, (value) => {
  if (value != null) emit("model-change", value);
});

// 草稿页的第一条消息：会话刚建好，进来就替它发出去
watch(
  () => props.initialMessage,
  (message) => {
    if (!message) return;
    emit("initial-consumed");
    void thread.send(message.input, message.attachments, message.resources ?? []);
  },
  { immediate: true },
);

watch(thread.running, (now, before) => {
  if (now) cancelEdit();
  if (before && !now) emit("run-end");
});

// 会话在别处被删了：把这个空壳退掉，别停在原地报 not found
watch(thread.missing, (gone) => {
  if (gone) emit("session-gone");
});

watch(thread.blocks, (blocks) => {
  if (editingBlock.value && !blocks.some((block) => block.id === editingBlock.value?.id)) {
    cancelEdit();
  }
});

watch(
  [thread.blocks, thread.running, interrupts],
  async () => {
    if (!pinned) return;
    await nextTick();
    const element = scroller.value;
    if (element) element.scrollTop = element.scrollHeight;
  },
  { flush: "post" },
);

watch(interrupts, async (value) => {
  if (value.length === 0) return;
  pinned = true;
  await nextTick();
  const element = scroller.value;
  if (element) element.scrollTop = element.scrollHeight;
});

function onScroll(event: Event) {
  const element = event.currentTarget as HTMLElement;
  const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
  // scrollTop 变小不一定是用户往上翻：浮窗挂上、顶部「生成中」出现都会压缩可视高度，
  // 浏览器会把 scrollTop 夹回去。只有紧跟在滚轮/触摸/按下之后的事件才算人的意图。
  if (distance <= 8) pinned = true;
  else if (userScrolled) pinned = false;
  userScrolled = false;
}

function markUserScroll() {
  userScrolled = true;
}

function chooseModel(modelId: number) {
  void thread.setModel(modelId);
}

function send(
  prompt: string,
  attachments: OutgoingAttachment[] = [],
  resources: OutgoingResource[] = [],
) {
  const target = editingBlock.value;
  if (!target) {
    void thread.send(prompt, attachments, resources);
    return;
  }
  editingBlock.value = null;
  draftBeforeEdit.value = "";
  void thread.editResend(target, prompt);
}

function startEdit(block: DisplayBlock, text: string) {
  if (pending.value || thread.running.value) return;
  if (!editingBlock.value) draftBeforeEdit.value = draft.value;
  editingBlock.value = block;
  draft.value = text;
  void nextTick(() => composer.value?.focus());
}

function cancelEdit() {
  if (!editingBlock.value) return;
  editingBlock.value = null;
  draft.value = draftBeforeEdit.value;
  draftBeforeEdit.value = "";
}

function submitApproval(payload: {
  interruptId: string;
  approvals: Record<string, boolean>;
  calls: Record<string, unknown>;
}) {
  void thread
    .answer(payload.interruptId, { approvals: payload.approvals, calls: payload.calls })
    .then((ok) => {
      if (ok) return;
      // 提交失败：放开认领、撤回这一批的「已收掉」，用户带着原答案重来
      pendingBatch.endSubmit(payload.interruptId);
      pendingBatch.reopen(
        interrupts.value.filter((item) => item.interrupt_id === payload.interruptId),
      );
    });
}

/** 向前翻页时补偿滚动高度，避免视图被新插入的内容顶走。 */
async function loadOlder() {
  const element = scroller.value;
  const beforeTop = element?.scrollTop ?? 0;
  const beforeHeight = element?.scrollHeight ?? 0;
  const added = await thread.loadOlder();
  if (!added || !element) return;
  await nextTick();
  element.scrollTop = beforeTop + (element.scrollHeight - beforeHeight);
}

const showEmpty = computed(
  () => !thread.loading.value && thread.blocks.value.length === 0 && !pending.value,
);

/** 主页「继续」不该把当前这条空会话自己也列进去。 */
const otherSessions = computed(() =>
  props.sessions.filter((session) => session.id !== props.sessionId),
);
</script>

<template>
  <section
    class="flex h-full min-w-[420px] flex-1 flex-col bg-canvas max-md:min-w-0"
  >
    <header
      v-if="!sidebarOpen || thread.running.value"
      class="flex h-11 shrink-0 items-center gap-2 px-2"
    >
      <button
        v-if="!sidebarOpen"
        class="rounded-control p-2 text-muted transition-colors hover:bg-hover hover:text-ink"
        title="展开侧栏"
        @click="emit('toggle-sidebar')"
      >
        <PanelLeft :size="17" :stroke-width="1.7" />
      </button>
      <span
        v-if="thread.running.value"
        class="flex items-center gap-1.5 text-meta text-faint"
      >
        <span class="size-1.5 animate-pulse rounded-full bg-accent" />
        生成中
      </span>
    </header>

    <div
      ref="scroller"
      class="min-h-0 flex-1 overflow-y-auto"
      @scroll="onScroll"
      @wheel="markUserScroll"
      @touchmove="markUserScroll"
      @pointerdown.self="markUserScroll"
    >
      <div v-if="showEmpty" class="rise flex h-full flex-col justify-center pb-4">
        <HomeWorkbench
          :groups="groups"
          :sessions="otherSessions"
          @open="emit('open-session', $event)"
          @new-in-group="emit('new-in-group', $event)"
          @create-group="emit('create-group', $event)"
        />
        <div
          v-if="activeModels.length === 0"
          class="mx-auto flex w-full max-w-[var(--measure)] items-center gap-3 px-5 text-meta text-muted"
        >
          <span>还没有可用模型。</span>
          <button
            class="font-medium text-ink underline underline-offset-2"
            @click="emit('open-settings')"
          >
            先配置一个
          </button>
        </div>
        <p
          v-if="thread.error.value"
          class="mx-auto w-full max-w-[var(--measure)] px-5 pt-3 text-meta text-warn"
        >
          {{ thread.error.value }}
        </p>
      </div>

      <div v-else-if="thread.loading.value" class="mx-auto flex h-full max-w-[var(--measure)] flex-col justify-center gap-3 px-6 pb-16">
        <div class="h-4 w-40 animate-pulse rounded bg-hover" />
        <div class="h-4 w-64 animate-pulse rounded bg-hover" />
        <div class="h-24 w-full animate-pulse rounded-float bg-inset" />
      </div>

      <div
        v-else
        :class="[
          'mx-auto flex max-w-[var(--measure)] flex-col gap-7 px-4 pt-6',
          // 浮窗是盖在正文上的，底部多留一截免得压住最后一行
          plan ? 'pb-16' : 'pb-5',
        ]"
      >
        <div v-if="thread.hasMore.value" class="flex justify-center pb-1">
          <button
            class="btn btn-ghost border border-hair"
            :disabled="thread.loadingOlder.value"
            @click="loadOlder"
          >
            {{ thread.loadingOlder.value ? "加载中…" : "加载更早的消息" }}
          </button>
        </div>
        <MessageRow
          v-for="(block, index) in thread.blocks.value"
          :key="block.id"
          :block="block"
          :running="thread.running.value"
          :pending="pending"
          :is-last="index === thread.blocks.value.length - 1"
          :editing="editingBlock?.id === block.id"
          @regenerate="(target) => void thread.regenerate(target)"
          @edit="startEdit"
          @branch="(leafId) => void thread.goBranch(leafId)"
        />

        <p v-if="thread.error.value" class="rounded-surface bg-warn/5 px-3 py-2 text-meta text-warn">
          {{ thread.error.value }}
        </p>
      </div>
    </div>

    <div class="relative shrink-0">
      <!-- 待办和待处理卡片都浮在输入框上方，不占正文高度；待办在最上面，卡片按到达顺序往下排 -->
      <div
        v-if="plan || pending"
        class="pointer-events-none absolute inset-x-0 bottom-full z-20 flex flex-col items-center gap-3 px-4 pb-2"
      >
        <PlanDock
          v-if="plan"
          :plan="plan"
          :running="thread.running.value"
          class="pointer-events-auto"
        />
        <ApprovalPanel
          v-if="pending"
          class="pointer-events-auto"
          :interrupts="interrupts"
          @submit="submitApproval"
        />
      </div>

      <ComposerBar
        ref="composer"
        v-model="draft"
        :running="thread.running.value"
        :editing="editingBlock !== null"
        :models="activeModels"
        :model-id="selectedModel"
        :model-disabled="thread.running.value || editingBlock !== null"
        :blocked="editingBlock ? false : !canSend || pending || hiddenPending"
        :blocked-reason="
          pending
            ? '先处理上方的卡片'
            : hiddenPending
              ? '还有未处理的卡片，先加载更早的消息'
              : activeModels.length === 0
                ? '先添加一个模型再开始'
                : '选择一个模型'
        "
        @send="send"
        @stop="thread.stop()"
        @cancel-edit="cancelEdit"
        @model-change="chooseModel"
        @manage-models="emit('open-settings')"
      />
    </div>
  </section>
</template>
