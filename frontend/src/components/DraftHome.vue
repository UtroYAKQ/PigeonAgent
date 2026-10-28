<script setup lang="ts">
import { PanelLeft } from "lucide-vue-next";
import { computed, ref } from "vue";

import ComposerBar from "./ComposerBar.vue";
import DriftingShapes from "./DriftingShapes.vue";
import ParticleField from "./ParticleField.vue";
import type { LlmModel, OutgoingAttachment, OutgoingResource } from "../types";

const props = defineProps<{
  models: LlmModel[];
  modelId: number | null;
  sidebarOpen: boolean;
}>();

const emit = defineEmits<{
  (
    event: "send",
    payload: { input: string; attachments: OutgoingAttachment[]; resources: OutgoingResource[] },
  ): void;
  (event: "model-change", modelId: number): void;
  (event: "toggle-sidebar"): void;
  (event: "open-settings"): void;
}>();

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const TITLE = "这次要处理什么？";

const draft = ref("");
const activeModels = computed(() => props.models.filter((model) => model.is_active));
const canSend = computed(() => activeModels.value.length > 0 && props.modelId != null);

const dateLine = computed(() => {
  const now = new Date();
  return `${WEEKDAYS[now.getDay()]} · ${now.getMonth() + 1} 月 ${now.getDate()} 日`;
});

function send(
  prompt: string,
  attachments: OutgoingAttachment[] = [],
  resources: OutgoingResource[] = [],
): void {
  const input = prompt.trim();
  if (!input && attachments.length === 0 && resources.length === 0) return;
  emit("send", { input, attachments, resources });
  draft.value = "";
}
</script>

<template>
  <section
    class="relative flex h-full min-w-[420px] flex-1 flex-col overflow-hidden bg-canvas max-md:min-w-0"
  >
    <DriftingShapes />
    <ParticleField />

    <header
      v-if="!sidebarOpen"
      class="relative z-10 flex h-11 shrink-0 items-center gap-2 px-2"
    >
      <button
        class="rounded-control p-2 text-muted transition-colors hover:bg-hover hover:text-ink"
        title="展开侧栏"
        @click="emit('toggle-sidebar')"
      >
        <PanelLeft :size="17" :stroke-width="1.7" />
      </button>
    </header>

    <div
      class="relative z-10 flex min-h-0 flex-1 flex-col items-center justify-center px-5 -translate-y-8"
    >
      <div class="flex flex-col items-center" data-particle-clear>
        <p class="rise text-meta tracking-[0.14em] text-faint">{{ dateLine }}</p>
        <h1 class="home-title text-display">
          <span
            v-for="(letter, index) in TITLE"
            :key="`${letter}-${index}`"
            class="home-title-letter"
            :style="{ animationDelay: `${120 + index * 32}ms` }"
          >{{ letter }}</span>
          <i class="home-title-rule" aria-hidden="true" />
        </h1>
      </div>
      <p v-if="activeModels.length === 0" class="flex items-center gap-3 pt-10 text-meta text-muted">
        还没有可用模型。
        <button
          class="font-medium text-ink underline underline-offset-2"
          @click="emit('open-settings')"
        >
          先配置一个
        </button>
      </p>
    </div>

    <div
      class="relative z-10 mx-auto w-full max-w-[calc(var(--measure)+2rem)]"
      data-particle-clear
    >
      <ComposerBar
        v-model="draft"
        :running="false"
        :models="activeModels"
        :model-id="modelId"
        :blocked="!canSend"
        :blocked-reason="activeModels.length === 0 ? '先添加一个模型再开始' : '选择一个模型'"
        @send="send"
        @model-change="emit('model-change', $event)"
        @manage-models="emit('open-settings')"
      />
    </div>
  </section>
</template>

<style scoped>
.home-title {
  position: relative;
  margin-top: 1rem;
}

/* 只在入场时逐字落位，之后标题不再动 */
.home-title-letter {
  display: inline-block;
  animation: title-in 0.5s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}

@keyframes title-in {
  from {
    opacity: 0;
    transform: translateY(0.36em);
    filter: blur(6px);
  }
}

.home-title-rule {
  position: absolute;
  left: 0;
  bottom: -12px;
  height: 1px;
  background: var(--accent);
  animation: rule-in 0.55s 0.38s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}

@keyframes rule-in {
  from {
    width: 0;
    opacity: 0;
  }
  to {
    width: 40px;
    opacity: 0.5;
  }
}

@media (prefers-reduced-motion: reduce) {
  .home-title-letter,
  .home-title-rule {
    animation: none;
  }

  .home-title-rule {
    width: 40px;
    opacity: 0.5;
  }
}
</style>
