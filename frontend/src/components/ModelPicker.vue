<script setup lang="ts">
import { Check, ChevronDown, Cpu, Settings2 } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import type { LlmModel } from "../types";

const props = defineProps<{
  models: LlmModel[];
  modelValue: number | null;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (event: "select", modelId: number): void;
  (event: "manage"): void;
}>();

const open = ref(false);
const root = ref<HTMLElement | null>(null);

const selected = computed(() => props.models.find((model) => model.id === props.modelValue) ?? null);

function toggle() {
  if (props.disabled) return;
  if (props.models.length === 0) {
    emit("manage");
    return;
  }
  open.value = !open.value;
}

function choose(model: LlmModel) {
  emit("select", model.id);
  open.value = false;
}

function onDocumentClick(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false;
}

onMounted(() => document.addEventListener("click", onDocumentClick));
onBeforeUnmount(() => document.removeEventListener("click", onDocumentClick));
</script>

<template>
  <div ref="root" class="relative">
    <button
      :class="[
        'btn btn-ghost max-w-56',
        disabled ? 'cursor-not-allowed opacity-50' : '',
      ]"
      @click="toggle"
    >
      <Cpu :size="13" :stroke-width="1.7" />
      <span class="max-w-40 truncate">{{ selected?.name ?? "选择模型" }}</span>
      <ChevronDown :size="12" :class="['transition-transform', open ? 'rotate-180' : '']" />
    </button>

    <div
      v-if="open"
      class="absolute bottom-[calc(100%+6px)] left-0 z-30 max-h-72 w-64 overflow-y-auto rounded-surface border border-hair bg-canvas p-1.5 shadow-float"
    >
      <button
        v-for="model in models"
        :key="model.id"
        class="flex w-full items-center gap-2 rounded-control px-2.5 py-2 text-left transition-colors hover:bg-hover"
        @click="choose(model)"
      >
        <span class="grid size-7 place-items-center rounded-control bg-inset text-micro font-semibold uppercase text-muted">
          {{ model.provider.slice(0, 2) }}
        </span>
        <span class="min-w-0">
          <span class="flex items-center gap-1.5">
            <span class="truncate text-meta text-ink">{{ model.name }}</span>
            <span v-if="model.is_default" class="chip chip-accent">默认</span>
          </span>
          <span class="block truncate font-mono text-micro text-faint">
            {{ model.model_name }}
          </span>
        </span>
        <Check v-if="model.id === modelValue" :size="14" class="ml-auto text-ink" />
      </button>
      <div class="my-1 h-px bg-hair" />
      <button
        class="flex w-full items-center gap-2 rounded-control px-2.5 py-2 text-left text-meta text-muted transition-colors hover:bg-hover hover:text-ink"
        @click="emit('manage'); open = false"
      >
        <Settings2 :size="14" :stroke-width="1.7" />
        管理模型
      </button>
    </div>
  </div>
</template>
