<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

const phrases = ['正在思考', '正在梳理线索', '正在组织回答', '马上就好']
const index = ref(0)
const timer = window.setInterval(() => {
  index.value = (index.value + 1) % phrases.length
}, 2600)

onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="flight-loader flex items-center gap-2 text-[12.5px] leading-5 text-muted-foreground">
    <svg
      class="flight-loader__spinner"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="7.4" stroke="currentColor" stroke-width="1.3" opacity="0.16" />
      <path
        d="M10 2.6 A7.4 7.4 0 0 1 16.4 6.3"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
      />
      <circle cx="10" cy="10" r="1.4" fill="currentColor" opacity="0.75" />
    </svg>
    <span class="relative block h-[18px] w-[88px] overflow-hidden" aria-live="polite">
      <Transition name="roll">
        <span :key="index" class="absolute inset-0">{{ phrases[index] }}</span>
      </Transition>
    </span>
  </div>
</template>

<style scoped>
.flight-loader__spinner {
  width: 16px;
  height: 16px;
  color: var(--foreground);
  animation: loader-spin 1.05s linear infinite;
}

.roll-enter-active,
.roll-leave-active {
  transition: transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
}

.roll-enter-from {
  transform: translateY(110%);
}

.roll-leave-to {
  transform: translateY(-110%);
}

@keyframes loader-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .flight-loader__spinner {
    animation-duration: 3.2s;
  }

  .roll-enter-active,
  .roll-leave-active {
    transition: none;
  }
}
</style>
