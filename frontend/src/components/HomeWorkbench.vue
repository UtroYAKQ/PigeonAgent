<script setup lang="ts">
import { computed, ref } from "vue";

import type { Session, SessionGroup } from "../types";

const props = defineProps<{
  sessions: Session[];
  groups: SessionGroup[];
  /** 从分组卡片进来的新聊天：第一条消息发出后才在该组建会话。 */
  groupId?: number | null;
}>();

const emit = defineEmits<{
  (event: "open", sessionId: string): void;
  (event: "new-in-group", groupId: number): void;
  (event: "create-group", name: string): void;
}>();

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

const dateLine = computed(() => {
  const now = new Date();
  const base = `${WEEKDAYS[now.getDay()]} · ${now.getMonth() + 1} 月 ${now.getDate()} 日`;
  const group = props.groups.find((item) => item.id === props.groupId);
  return group ? `${base} · 新会话会放进「${group.name}」` : base;
});

const recent = computed(() => props.sessions.slice(0, 4));

const creating = ref(false);
const draft = ref("");

function submit(): void {
  const name = draft.value.trim();
  creating.value = false;
  draft.value = "";
  if (name) emit("create-group", name);
}

function titleOf(session: Session): string {
  return session.title?.trim() || "未命名会话";
}

function groupName(session: Session): string {
  return props.groups.find((group) => group.id === session.group_id)?.name ?? "";
}

function agoOf(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} 小时前`;
  return `${Math.round(minutes / (60 * 24))} 天前`;
}

/** 组卡片里预览该组最近两条；列表已按最近活跃排好。 */
function topOf(group: SessionGroup): Session[] {
  return props.sessions.filter((session) => session.group_id === group.id).slice(0, 2);
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-[var(--measure)] flex-col gap-7 px-5 pt-10 pb-6">
    <div>
      <p class="text-meta text-faint">{{ dateLine }}</p>
      <h1 class="mt-1.5 text-display leading-tight tracking-[-0.015em] text-ink">
        接着哪儿干？<span class="font-normal text-faint">或者开一条新的。</span>
      </h1>
    </div>

    <div class="grid gap-8 min-[820px]:grid-cols-[1.05fr_1fr]">
      <section>
        <header class="flex items-baseline gap-2 text-meta text-faint">
          <span class="text-meta font-medium text-ink">继续</span>
          <span>最近活跃的 {{ recent.length }} 条</span>
        </header>
        <ul class="mt-1 divide-y divide-hair">
          <li v-for="(session, index) in recent" :key="session.id">
            <button
              class="flex w-full items-start gap-2.5 rounded-control px-2 py-2.5 text-left transition-colors hover:bg-inset"
              @click="emit('open', session.id)"
            >
              <span class="w-4 shrink-0 pt-[3px] font-mono text-micro text-faint">
                {{ String(index + 1).padStart(2, "0") }}
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-ui text-ink">{{ titleOf(session) }}</span>
                <span class="mt-0.5 block truncate text-micro text-faint">
                  {{ groupName(session) || "未分组" }} · {{ agoOf(session.last_run_at) }}
                </span>
              </span>
              <span
                v-if="groupName(session)"
                class="mt-0.5 shrink-0 rounded-full border border-hair px-2 py-0.5 text-micro text-faint"
              >
                {{ groupName(session) }}
              </span>
            </button>
          </li>
          <li v-if="recent.length === 0" class="px-2 py-3 text-meta text-faint">
            还没有会话，直接在下面输入框里说一句就行。
          </li>
        </ul>
      </section>

      <section>
        <header class="flex items-baseline gap-2 text-meta text-faint">
          <span class="text-meta font-medium text-ink">分组</span>
          <span>点卡片就在组里开新会话</span>
        </header>
        <div class="mt-2 grid gap-2.5 min-[560px]:grid-cols-2">
          <button
            v-for="group in groups"
            :key="group.id"
            class="rounded-surface border border-hair bg-surface p-3 text-left transition-colors hover:bg-inset"
            @click="emit('new-in-group', group.id)"
          >
            <div class="flex items-center gap-2">
              <span class="size-2 shrink-0 rounded-[3px] border border-accent/30 bg-accent-soft" />
              <span class="min-w-0 flex-1 truncate text-meta font-medium text-ink">
                {{ group.name }}
              </span>
              <span class="num shrink-0 text-micro text-faint">{{ group.session_count }}</span>
            </div>
            <ul class="mt-2 space-y-1">
              <li
                v-for="session in topOf(group)"
                :key="session.id"
                class="truncate text-meta text-muted"
              >
                {{ titleOf(session) }}
              </li>
              <li v-if="topOf(group).length === 0" class="text-meta text-faint">
                还没有会话
              </li>
            </ul>
          </button>

          <div
            v-if="creating"
            class="rounded-surface border border-accent/50 bg-canvas p-3"
          >
            <input
              v-model="draft"
              maxlength="60"
              placeholder="分组名，回车创建"
              class="w-full bg-transparent text-meta outline-none placeholder:text-faint"
              @keydown.enter.prevent="submit"
              @keydown.esc.prevent="((creating = false), (draft = ''))"
              @blur="submit"
            />
          </div>
          <button
            v-else
            class="flex flex-col items-start gap-1.5 rounded-surface border border-dashed border-hair bg-canvas p-3 text-left transition-colors hover:bg-inset"
            @click="creating = true"
          >
            <span class="text-ui leading-none text-faint">＋</span>
            <span class="text-meta text-faint">新建分组</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
