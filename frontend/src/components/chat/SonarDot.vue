<script setup lang="ts">
withDefaults(defineProps<{
  size?: number
  tone?: 'brand' | 'ink' | 'muted'
  speed?: number
}>(), {
  size: 6,
  tone: 'muted',
  speed: 1.9,
})
</script>

<template>
  <span
    class="sonar-dot"
    :class="`sonar-dot--${tone}`"
    :style="{ '--core': `${size}px`, '--speed': `${speed}s` }"
    aria-hidden="true"
  >
    <span class="sonar-dot__core" />
  </span>
</template>

<style scoped>
.sonar-dot {
  position: relative;
  display: inline-flex;
  width: var(--core);
  height: var(--core);
  flex: none;
  color: rgba(128, 128, 134, 0.55);
}

.sonar-dot--brand {
  color: var(--brand);
}

.sonar-dot--ink {
  color: var(--foreground);
}

.sonar-dot__core {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: currentColor;
}

.sonar-dot::before,
.sonar-dot::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 999px;
  border: 1px solid currentColor;
  opacity: 0;
  animation: sonar-ring var(--speed) cubic-bezier(0.16, 0.6, 0.3, 1) infinite;
  pointer-events: none;
}

.sonar-dot::after {
  animation-delay: calc(var(--speed) / -2);
}

@keyframes sonar-ring {
  0% {
    transform: scale(1);
    opacity: 0.5;
  }
  72%,
  100% {
    transform: scale(3.2);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sonar-dot::before,
  .sonar-dot::after {
    animation: none;
  }
}
</style>
