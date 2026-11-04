<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMouseInElement } from '@vueuse/core'

const field = ref<HTMLElement | null>(null)
const { elementX, elementY, elementWidth, elementHeight, isOutside } = useMouseInElement(field)

const style = computed(() => {
  const width = Math.max(elementWidth.value, 1)
  const height = Math.max(elementHeight.value, 1)
  const x = Math.min(Math.max(elementX.value, 0), width)
  const y = Math.min(Math.max(elementY.value, 0), height)
  return {
    '--cursor-x': `${x}px`,
    '--cursor-y': `${y}px`,
    '--cursor-opacity': isOutside.value ? '0' : '1',
    '--mx': (x / width - 0.5).toFixed(4),
    '--my': (y / height - 0.5).toFixed(4),
  }
})
</script>

<template>
  <div ref="field" class="flight-field" :style="style" aria-hidden="true">
    <div class="flight-field__dots" />
    <div class="flight-field__dots flight-field__dots--hot" />

    <div class="flight-field__dove" />
  </div>
</template>

<style scoped>
.flight-field {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  color: var(--foreground);
}

.flight-field__dots {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(
    circle,
    color-mix(in srgb, var(--foreground) 16%, transparent) 1.15px,
    transparent 1.4px
  );
  background-size: 22px 22px;
  opacity: 0.72;
  mask-image: radial-gradient(ellipse 96% 92% at 50% 45%, #000 62%, transparent 100%);
  -webkit-mask-image: radial-gradient(ellipse 96% 92% at 50% 45%, #000 62%, transparent 100%);
}

.flight-field__dots--hot {
  background-image: radial-gradient(
    circle,
    color-mix(in srgb, var(--foreground) 22%, transparent) 1.25px,
    transparent 1.5px
  );
  opacity: calc(var(--cursor-opacity, 0) * 1.15);
  mask-image: radial-gradient(
    240px circle at var(--cursor-x, 0px) var(--cursor-y, 0px),
    #000 0%,
    rgba(0, 0, 0, 0.55) 48%,
    transparent 100%
  );
  -webkit-mask-image: radial-gradient(
    240px circle at var(--cursor-x, 0px) var(--cursor-y, 0px),
    #000 0%,
    rgba(0, 0, 0, 0.55) 48%,
    transparent 100%
  );
  transition: opacity 260ms ease;
}

.flight-field__dove {
  position: absolute;
  top: -4%;
  right: -4%;
  width: clamp(440px, 47vw, 720px);
  aspect-ratio: 1;
  background-image: radial-gradient(circle, currentColor 1.2px, transparent 1.35px);
  background-size: 7px 7px;
  opacity: 0.18;
  -webkit-mask: url('/logo.png') center / contain no-repeat;
  mask: url('/logo.png') center / contain no-repeat;
  translate: calc(var(--mx, 0) * -16px) calc(var(--my, 0) * -11px);
  animation: flight-dove-drift 24s ease-in-out infinite alternate;
  will-change: transform, translate;
}

@keyframes flight-dove-drift {
  from {
    transform: translate3d(0, 0, 0) rotate(-1.6deg) scale(0.98);
  }
  to {
    transform: translate3d(-24px, 22px, 0) rotate(2.4deg) scale(1.025);
  }
}

@media (max-width: 1080px) {
  .flight-field__dove {
    top: 0%;
    right: -10%;
    width: 440px;
    opacity: 0.13;
  }
}

@media (max-width: 767px) {
  .flight-field__dove {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .flight-field__dove {
    animation: none !important;
  }

  .flight-field__dots--hot {
    transition: none;
  }
}
</style>
