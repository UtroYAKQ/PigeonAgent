<script setup lang="ts">
import { FolderInput, Pencil, Trash2 } from "lucide-vue-next";

import type { Session, SessionGroup } from "../types";

const props = defineProps<{
  session: Session;
  active: boolean;
  groups: SessionGroup[];
  /** 重命名和移动菜单一次只能开一个，状态由侧栏统一拿着。 */
  editing: boolean;
  draft: string;
  menuOpen: boolean;
}>();

const emit = defineEmits<{
  (event: "select", sessionId: string): void;
  (event: "remove", session: Session): void;
  (event: "move", session: Session, groupId: number | null): void;
  (event: "start-edit", session: Session): void;
  (event: "update:draft", value: string): void;
  (event: "commit"): void;
  (event: "cancel"): void;
  (event: "toggle-menu", sessionId: string): void;
}>();

function titleOf(session: Session): string {
  return session.title?.trim() || "未命名会话";
}

const moveTargets = (
  session: Session,
): { id: number | null; name: string; current: boolean }[] => [
  { id: null, name: "未分组" },
  ...props.groups.map((group) => ({ id: group.id, name: group.name })),
].map((option) => ({ ...option, current: option.id === session.group_id }));
</script>

<template>
  <li class="group relative">
    <input
      v-if="editing"
      :value="draft"
      data-rename-input
      maxlength="120"
      class="w-full truncate rounded-control border border-accent/50 bg-canvas px-2.5 py-2 text-ui text-ink outline-none"
      @input="emit('update:draft', ($event.target as HTMLInputElement).value)"
      @keydown.enter.prevent="emit('commit')"
      @keydown.esc.prevent="emit('cancel')"
      @blur="emit('commit')"
    />
    <button
      v-else
      :class="[
        'relative w-full truncate rounded-control px-2.5 py-2 pr-16 text-left text-ui transition-colors',
        active
          ? 'bg-hover font-medium text-ink before:absolute before:top-1.5 before:bottom-1.5 before:left-[-9px] before:w-[2px] before:rounded-full before:bg-ink'
          : 'text-ink/90 hover:bg-hover/70',
      ]"
      @click="emit('select', session.id)"
    >
      <span
        v-if="session.pending_batches"
        class="mr-1.5 inline-block size-1.5 rounded-full bg-accent align-middle"
      />
      {{ titleOf(session) }}
    </button>

    <div
      v-if="!editing"
      class="absolute right-1 top-1/2 flex -translate-y-1/2 items-center opacity-0 transition-opacity pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto focus-within:opacity-100 focus-within:pointer-events-auto max-md:opacity-100 max-md:pointer-events-auto"
    >
      <button
        class="relative rounded-control p-1.5 text-faint hover:bg-hover hover:text-ink"
        title="移动到分组"
        @click.stop="emit('toggle-menu', session.id)"
      >
        <FolderInput :size="13" :stroke-width="1.7" />
        <div
          v-if="menuOpen"
          class="absolute right-0 top-8 z-20 w-44 rounded-surface border border-hair bg-canvas p-1 text-left shadow-float"
          @click.stop
        >
          <p class="px-2 pt-1 pb-0.5 text-micro text-faint">移动到分组</p>
          <button
            v-for="option in moveTargets(session)"
            :key="String(option.id)"
            :class="[
              'flex w-full items-center gap-2 truncate rounded-control px-2 py-1.5 text-meta transition-colors hover:bg-hover',
              option.current ? 'text-ink' : 'text-muted',
            ]"
            @click="emit('move', session, option.id)"
          >
            <span class="min-w-0 flex-1 truncate">{{ option.name }}</span>
            <span v-if="option.current" class="shrink-0 text-micro text-accent">✓</span>
          </button>
        </div>
      </button>
      <button
        class="rounded-control p-1.5 text-faint hover:bg-hover hover:text-ink"
        title="重命名"
        @click="emit('start-edit', session)"
      >
        <Pencil :size="13" :stroke-width="1.7" />
      </button>
      <button
        class="rounded-control p-1.5 text-faint hover:bg-hover hover:text-warn"
        title="删除"
        @click="emit('remove', session)"
      >
        <Trash2 :size="13" :stroke-width="1.7" />
      </button>
    </div>
  </li>
</template>
