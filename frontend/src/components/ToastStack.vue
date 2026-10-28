<script setup lang="ts">
import { CircleAlert, Info, X } from "lucide-vue-next";
import { onBeforeUnmount, onMounted, ref } from "vue";

import { bindToastHost, dismissToast, toasts } from "../lib/toast";

const host = ref<HTMLElement | null>(null);

onMounted(() => bindToastHost(host.value));
onBeforeUnmount(() => bindToastHost(null));
</script>

<template>
  <div ref="host" popover="manual" class="toast-host">
    <TransitionGroup name="toast" tag="div" class="flex flex-col items-center gap-2 px-4 pt-3">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :role="toast.kind === 'error' ? 'alert' : 'status'"
        class="pointer-events-auto flex w-full max-w-[26rem] items-start gap-2.5 rounded-surface border border-hair bg-canvas py-2.5 pl-3.5 pr-2 text-meta shadow-float"
      >
        <CircleAlert
          v-if="toast.kind === 'error'"
          :size="15"
          :stroke-width="1.7"
          class="mt-0.5 shrink-0 text-warn"
        />
        <Info v-else :size="15" :stroke-width="1.7" class="mt-0.5 shrink-0 text-accent" />
        <p class="min-w-0 flex-1 whitespace-pre-wrap break-words leading-5 text-ink">
          {{ toast.message }}
        </p>
        <button
          class="rounded-control p-1 text-faint transition-colors hover:bg-hover hover:text-ink"
          aria-label="关闭提示"
          @click="dismissToast(toast.id)"
        >
          <X :size="13" :stroke-width="1.7" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  inset: 0 0 auto;
  width: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  overflow: visible;
  z-index: 80;
}

.toast-enter-active,
.toast-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active {
    transition: none;
  }
}
</style>
