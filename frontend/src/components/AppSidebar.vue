<script setup lang="ts">
import {
  Bird,
  ChevronDown,
  ChevronRight,
  LogOut,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
  Settings2,
  SquarePen,
} from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import SessionRow from "./SessionRow.vue";
import type { Session, SessionGroup } from "../types";

const props = defineProps<{
  sessions: Session[];
  groups: SessionGroup[];
  collapsed: number[];
  activeId: string | null;
  user: { email: string; display_name: string | null } | null;
}>();

const emit = defineEmits<{
  (event: "select", sessionId: string): void;
  (event: "new", groupId?: number): void;
  (event: "collapse"): void;
  (event: "rename", sessionId: string, title: string): void;
  (event: "remove", session: Session): void;
  (event: "move", session: Session, groupId: number | null): void;
  (event: "create-group", name: string): void;
  (event: "rename-group", groupId: number, name: string): void;
  (event: "remove-group", group: SessionGroup): void;
  (event: "toggle-group", groupId: number): void;
  (event: "settings"): void;
  (event: "profile"): void;
  (event: "logout"): void;
}>();

const collapsedSet = computed(() => new Set(props.collapsed));
const userInitial = computed(() => {
  const name = props.user?.display_name?.trim() || props.user?.email || "P";
  return name.charAt(0).toUpperCase();
});

/* ------------------------------------------------------------- 会话行状态 */

const editingSession = ref<string | null>(null);
const draft = ref("");
const moveMenuFor = ref<string | null>(null);

function startRename(session: Session): void {
  moveMenuFor.value = null;
  groupMenuFor.value = null;
  editingSession.value = session.id;
  draft.value = session.title ?? "";
  focusInput();
}

function commitRename(): void {
  const sessionId = editingSession.value;
  if (!sessionId) return;
  editingSession.value = null;
  const title = draft.value.trim();
  const current = props.sessions.find((session) => session.id === sessionId)?.title;
  if (title && title !== current) emit("rename", sessionId, title);
}

/* ------------------------------------------------------------- 分组行状态 */

const creatingGroup = ref(false);
const groupDraft = ref("");
const editingGroup = ref<number | null>(null);
const groupMenuFor = ref<number | null>(null);

function submitNewGroup(): void {
  const name = groupDraft.value.trim();
  creatingGroup.value = false;
  groupDraft.value = "";
  if (name) emit("create-group", name);
}

function startGroupRename(group: SessionGroup): void {
  moveMenuFor.value = null;
  groupMenuFor.value = null;
  editingGroup.value = group.id;
  draft.value = group.name;
  focusInput();
}

function commitGroupRename(): void {
  const groupId = editingGroup.value;
  if (groupId == null) return;
  editingGroup.value = null;
  const name = draft.value.trim();
  if (name && name !== props.groups.find((group) => group.id === groupId)?.name) {
    emit("rename-group", groupId, name);
  }
}

function focusInput(): void {
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>("[data-rename-input]");
    input?.focus();
    input?.select();
  });
}

/** 浮层菜单：点外面就关，一次只开一个。 */
function closeMenus(): void {
  moveMenuFor.value = null;
  groupMenuFor.value = null;
}

watch([moveMenuFor, groupMenuFor], ([move, menu]) => {
  if (move == null && menu == null) {
    document.removeEventListener("click", closeMenus);
    return;
  }
  document.addEventListener("click", closeMenus);
});

onBeforeUnmount(() => document.removeEventListener("click", closeMenus));

/* ---------------------------------------------------------------- 列表 */

const grouped = computed(() =>
  props.groups.map((group) => ({
    group,
    items: props.sessions.filter((session) => session.group_id === group.id),
  })),
);

/** 没分组的会话继续按时间归档，保住「今天聊了什么」这个入口。 */
const timeBuckets = computed(() => {
  const buckets = new Map<string, Session[]>();
  for (const session of props.sessions.filter((item) => item.group_id == null)) {
    const key = bucketOf(session.last_run_at ?? session.updated_at);
    buckets.set(key, [...(buckets.get(key) ?? []), session]);
  }
  return [...buckets.entries()];
});

function bucketOf(updatedAt: string): string {
  const days = (Date.now() - new Date(updatedAt).getTime()) / 86_400_000;
  if (days < 1) return "今天";
  if (days < 7) return "过去 7 天";
  if (days < 30) return "过去 30 天";
  return "更早";
}
</script>

<template>
  <aside class="flex h-full w-[272px] shrink-0 flex-col bg-pane">
    <div class="flex items-center gap-2 px-3 pt-3 pb-2">
      <div class="grid size-8 place-items-center rounded-control bg-ink text-canvas">
        <Bird :size="17" :stroke-width="1.7" />
      </div>
      <div class="truncate text-ui font-semibold tracking-tight">PigeonAgent</div>
      <button
        class="ml-auto rounded-control p-1.5 text-muted transition-colors hover:bg-hover hover:text-ink"
        title="收起侧栏"
        @click="emit('collapse')"
      >
        <PanelLeftClose :size="17" :stroke-width="1.7" />
      </button>
    </div>

    <div class="px-3 pt-1 pb-2">
      <button
        class="flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-ui text-ink transition-colors hover:bg-hover"
        @click="emit('new')"
      >
        <SquarePen :size="16" :stroke-width="1.7" />
        新聊天
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto px-2.5 pb-3">
      <div class="flex items-center gap-2 px-1 pt-2">
        <span class="text-micro text-faint">分组</span>
        <button
          class="ml-auto flex items-center gap-1 rounded-control px-1.5 py-1 text-micro text-faint transition-colors hover:bg-hover hover:text-ink"
          @click="creatingGroup = true"
        >
          <Plus :size="12" :stroke-width="1.7" />
          新建分组
        </button>
      </div>
      <input
        v-if="creatingGroup"
        v-model="groupDraft"
        maxlength="60"
        placeholder="分组名，回车创建"
        class="mt-1.5 w-full rounded-control border border-accent/50 bg-canvas px-2.5 py-1.5 text-meta outline-none"
        @keydown.enter.prevent="submitNewGroup"
        @keydown.esc.prevent="((creatingGroup = false), (groupDraft = ''))"
        @blur="submitNewGroup"
      />

      <div v-for="{ group, items } in grouped" :key="group.id" class="mt-2">
        <div
          class="group/head flex cursor-pointer items-center gap-1 rounded-control px-1 py-1 hover:bg-hover"
          @click="emit('toggle-group', group.id)"
        >
          <button class="flex min-w-0 flex-1 items-center gap-1 text-left">
            <ChevronRight v-if="collapsedSet.has(group.id)" :size="12" class="shrink-0 text-faint" />
            <ChevronDown v-else :size="12" class="shrink-0 text-faint" />
            <input
              v-if="editingGroup === group.id"
              v-model="draft"
              data-rename-input
              maxlength="60"
              class="min-w-0 flex-1 rounded border border-accent/50 bg-canvas px-1.5 py-0.5 text-meta font-medium outline-none"
              @click.stop
              @keydown.enter.prevent="commitGroupRename"
              @keydown.esc.prevent="editingGroup = null"
              @blur="commitGroupRename"
            />
            <span v-else class="truncate text-meta font-medium text-muted">{{ group.name }}</span>
            <span class="num shrink-0 text-micro text-faint">{{ group.session_count }}</span>
          </button>
          <div
            v-if="editingGroup !== group.id"
            class="flex shrink-0 items-center opacity-0 transition-opacity pointer-events-none group-hover/head:pointer-events-auto group-hover/head:opacity-100 focus-within:opacity-100 focus-within:pointer-events-auto max-md:opacity-100 max-md:pointer-events-auto"
          >
            <button
              class="rounded-control p-1 text-faint hover:bg-canvas hover:text-ink"
              :title="`在「${group.name}」里新聊天`"
              @click.stop="emit('new', group.id)"
            >
              <Plus :size="13" :stroke-width="1.7" />
            </button>
            <button
              class="relative rounded-control p-1 text-faint hover:bg-canvas hover:text-ink"
              title="分组选项"
              @click.stop="groupMenuFor = groupMenuFor === group.id ? null : group.id"
            >
              <MoreHorizontal :size="13" />
              <div
                v-if="groupMenuFor === group.id"
                class="absolute right-0 top-6 z-20 w-32 rounded-surface border border-hair bg-canvas p-1 shadow-float"
                @click.stop
              >
                <button
                  class="w-full rounded-control px-2 py-1.5 text-left text-meta text-muted hover:bg-hover hover:text-ink"
                  @click="startGroupRename(group)"
                >
                  重命名
                </button>
                <button
                  class="w-full rounded-control px-2 py-1.5 text-left text-meta text-warn hover:bg-hover"
                  @click="((groupMenuFor = null), emit('remove-group', group))"
                >
                  删除分组
                </button>
              </div>
            </button>
          </div>
        </div>

        <ul v-if="!collapsedSet.has(group.id)" class="ml-[7px] mt-0.5 space-y-0.5 border-l border-hair pl-1.5">
          <li v-if="items.length === 0" class="px-2 py-1.5 text-meta text-faint">
            空分组 · 点 ＋ 开第一条
          </li>
          <SessionRow
            v-for="session in items"
            :key="session.id"
            :session="session"
            :groups="groups"
            :active="session.id === activeId"
            :editing="editingSession === session.id"
            :draft="draft"
            :menu-open="moveMenuFor === session.id"
            @select="emit('select', $event)"
            @remove="emit('remove', $event)"
            @move="(target, groupId) => emit('move', target, groupId)"
            @start-edit="startRename"
            @update:draft="draft = $event"
            @commit="commitRename"
            @cancel="editingSession = null"
            @toggle-menu="moveMenuFor = moveMenuFor === $event ? null : $event"
          />
        </ul>
      </div>

      <div v-for="[label, items] in timeBuckets" :key="label" class="mb-1">
        <div class="group/bucket flex items-center gap-1 rounded-control px-1.5 pt-4 pb-1.5">
          <h2 class="text-micro font-medium tracking-wide text-faint">{{ label }}</h2>
          <button
            class="ml-auto rounded-control p-1 text-faint opacity-0 transition-opacity pointer-events-none group-hover/bucket:pointer-events-auto group-hover/bucket:opacity-100 hover:bg-hover hover:text-ink max-md:opacity-100 max-md:pointer-events-auto"
            title="新聊天，不进任何分组"
            @click="emit('new')"
          >
            <Plus :size="13" :stroke-width="1.7" />
          </button>
        </div>
        <ul class="space-y-0.5">
          <SessionRow
            v-for="session in items"
            :key="session.id"
            :session="session"
            :groups="groups"
            :active="session.id === activeId"
            :editing="editingSession === session.id"
            :draft="draft"
            :menu-open="moveMenuFor === session.id"
            @select="emit('select', $event)"
            @remove="emit('remove', $event)"
            @move="(target, groupId) => emit('move', target, groupId)"
            @start-edit="startRename"
            @update:draft="draft = $event"
            @commit="commitRename"
            @cancel="editingSession = null"
            @toggle-menu="moveMenuFor = moveMenuFor === $event ? null : $event"
          />
        </ul>
      </div>

      <p v-if="sessions.length === 0" class="px-3 pt-8 text-ui leading-6 text-faint">
        还没有会话。<br />发一条消息，Pigeon 会帮你把过程记下来。
      </p>
    </nav>

    <div class="border-t border-hair px-3 py-2.5">
      <button
        class="flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-meta text-muted transition-colors hover:bg-hover hover:text-ink"
        @click="emit('settings')"
      >
        <Settings2 :size="15" :stroke-width="1.7" />
        设置
      </button>
      <div v-if="user" class="mt-0.5 flex items-center gap-0.5">
        <button
          class="flex min-w-0 flex-1 items-center gap-2 rounded-control px-2.5 py-1.5 text-left text-meta text-muted transition-colors hover:bg-hover hover:text-ink"
          title="账号设置"
          @click="emit('profile')"
        >
          <span
            class="grid size-6 shrink-0 place-items-center rounded-full border border-hair bg-canvas text-micro font-medium text-muted"
          >
            {{ userInitial }}
          </span>
          <span class="min-w-0 flex-1 truncate" :title="user.email">
            {{ user.display_name || user.email }}
          </span>
        </button>
        <button
          class="shrink-0 rounded-control p-1.5 text-faint transition-colors hover:bg-hover hover:text-ink"
          title="退出登录"
          aria-label="退出登录"
          @click="emit('logout')"
        >
          <LogOut :size="13" :stroke-width="1.7" />
        </button>
      </div>
    </div>
  </aside>
</template>
