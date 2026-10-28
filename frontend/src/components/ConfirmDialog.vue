<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";

defineProps<{
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
}>();

const emit = defineEmits<{
  (event: "confirm"): void;
  (event: "cancel"): void;
}>();
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button class="absolute inset-0 bg-black/30 backdrop-blur-[2px]" aria-label="取消" @click="emit('cancel')" />
      <div class="relative w-full max-w-sm rounded-float border border-hair bg-canvas p-5 shadow-modal">
        <div class="flex items-start gap-3">
          <div class="grid size-9 shrink-0 place-items-center rounded-surface bg-warn/10 text-warn">
            <AlertTriangle :size="17" :stroke-width="1.7" />
          </div>
          <div>
            <h2 class="text-ui font-semibold text-ink">{{ title }}</h2>
            <p class="mt-1 text-meta leading-5 text-muted">{{ message }}</p>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button
            class="btn btn-ghost border border-hair"
            @click="emit('cancel')"
          >
            取消
          </button>
          <button
            class="btn btn-danger-solid"
            @click="emit('confirm')"
          >
            {{ confirmLabel ?? "删除" }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
