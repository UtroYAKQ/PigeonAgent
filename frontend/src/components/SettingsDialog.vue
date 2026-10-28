<script setup lang="ts">
import { Cpu, Settings2, UserRound, X } from "lucide-vue-next";
import { onMounted, ref, watch, type Component } from "vue";

import ModelsPanel from "./settings/ModelsPanel.vue";
import ProfilePanel from "./settings/ProfilePanel.vue";
import { raiseToasts } from "../lib/toast";
import type { LlmModel, SettingsSection, UserRead } from "../types";

defineProps<{ models: LlmModel[]; user: UserRead | null }>();

const emit = defineEmits<{
  (event: "changed"): void;
  (event: "logout"): void;
}>();

const open = defineModel<boolean>("open", { required: true });
const section = defineModel<SettingsSection>("section", { default: "models" });

interface SettingsNav {
  id: SettingsSection;
  label: string;
  icon: Component;
}

/** 左侧目录：加栏目 = 这里加一项 + 下方加一个分支。 */
const SECTIONS: SettingsNav[] = [
  { id: "profile", label: "个人", icon: UserRound },
  { id: "models", label: "模型配置", icon: Cpu },
];

const dialog = ref<HTMLDialogElement | null>(null);

watch(open, (value) => {
  const element = dialog.value;
  if (!element) return;
  if (value && !element.open) {
    element.showModal();
    // 模态有自己的 top layer；消息条要重新入栈才不会压在遮罩下面
    raiseToasts();
    element.focus();
  }
  if (!value && element.open) element.close();
});

onMounted(() => {
  if (open.value) dialog.value?.showModal();
});

function close(): void {
  open.value = false;
}
</script>

<template>
  <dialog
    ref="dialog"
    class="settings-dialog"
    tabindex="-1"
    aria-labelledby="settings-title"
    @close="open = false"
    @click.self="close"
    @cancel.prevent="close"
  >
    <div class="flex h-full min-h-0 flex-col">
      <header class="flex shrink-0 items-center gap-3 border-b border-hair px-5 py-3.5">
        <div class="grid size-8 place-items-center rounded-control bg-inset text-muted">
          <Settings2 :size="16" :stroke-width="1.7" />
        </div>
        <div>
          <h2 id="settings-title" class="text-body font-semibold text-ink">设置</h2>
          <p class="text-meta text-faint">账号与模型都在这里管理</p>
        </div>
        <button
          class="ml-auto rounded-control p-2 text-faint transition-colors hover:bg-hover hover:text-ink"
          title="关闭"
          @click="close"
        >
          <X :size="17" :stroke-width="1.7" />
        </button>
      </header>

      <div class="flex min-h-0 flex-1 max-sm:flex-col">
        <nav
          class="flex w-44 shrink-0 flex-col gap-0.5 border-r border-hair bg-pane p-2.5 max-sm:w-full max-sm:flex-row max-sm:border-b max-sm:border-r-0 max-sm:p-2"
        >
          <button
            v-for="item in SECTIONS"
            :key="item.id"
            :class="[
              'flex items-center gap-2 rounded-control border px-2.5 py-2 text-left text-ui transition-colors',
              section === item.id
                ? 'border-hair bg-canvas font-medium text-ink'
                : 'border-transparent text-muted hover:bg-hover hover:text-ink',
            ]"
            @click="section = item.id"
          >
            <component :is="item.icon" :size="15" :stroke-width="1.7" />
            {{ item.label }}
          </button>
          <p class="mt-auto px-2.5 pt-4 text-micro text-faint max-sm:hidden">PigeonAgent</p>
        </nav>

        <section class="min-h-0 min-w-0 flex-1">
          <ProfilePanel v-if="section === 'profile'" :user="user" @logout="emit('logout')" />
          <ModelsPanel
            v-else-if="section === 'models'"
            :models="models"
            @changed="emit('changed')"
          />
        </section>
      </div>
    </div>
  </dialog>
</template>
