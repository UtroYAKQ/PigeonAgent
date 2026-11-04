<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

import BrandMark from '@/components/brand/BrandMark.vue'

const now = new Date()
const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][now.getDay()]
const todayLabel = `${weekday} · ${now.getMonth() + 1}月${now.getDate()}日`

const TITLE = '行于未竟，止于未知'
const TYPE_DELAY = 340
const TYPE_INTERVAL = 140
const HOLD_DURATION = 10000
const DELETE_INTERVAL = 80
const REST_DURATION = 10000

type Phase = 'typing' | 'holding' | 'deleting' | 'resting'

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const typed = ref(reducedMotion ? TITLE : '')
const phase = ref<Phase>(reducedMotion ? 'holding' : 'typing')
let timer: number | null = null
let index = 0

function schedule(next: () => void, delay: number): void {
  timer = window.setTimeout(next, delay)
}

function typeNext(): void {
  index += 1
  typed.value = TITLE.slice(0, index)
  if (index < TITLE.length) {
    schedule(typeNext, TYPE_INTERVAL)
    return
  }
  phase.value = 'holding'
  schedule(startDelete, HOLD_DURATION)
}

function startDelete(): void {
  phase.value = 'deleting'
  schedule(deleteNext, DELETE_INTERVAL)
}

function deleteNext(): void {
  index -= 1
  typed.value = TITLE.slice(0, index)
  if (index > 0) {
    schedule(deleteNext, DELETE_INTERVAL)
    return
  }
  phase.value = 'resting'
  schedule(startType, REST_DURATION)
}

function startType(): void {
  phase.value = 'typing'
  index = 1
  typed.value = TITLE.slice(0, index)
  schedule(typeNext, TYPE_INTERVAL)
}

if (!reducedMotion) {
  schedule(() => {
    index = 1
    typed.value = TITLE.slice(0, index)
    schedule(typeNext, TYPE_INTERVAL)
  }, TYPE_DELAY)
}

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})
</script>

<template>
  <div class="hero-stage fade-in">
    <p class="mb-6 text-[10.5px] font-medium tracking-[0.17em] text-muted-foreground/60">
      {{ todayLabel }}
    </p>
    <div class="flex items-center justify-center gap-3.5 sm:gap-4">
      <BrandMark size="lg" class="relative z-10" />
      <h1
        v-if="typed.length > 0"
        class="font-title min-h-[1.2em] text-left text-[24px] font-normal leading-tight tracking-normal sm:text-[30px]"
      >
        {{ typed }}<span v-if="typed.length > 0 && (phase === 'typing' || phase === 'deleting')" class="type-caret" aria-hidden="true" />
      </h1>
    </div>
    <span class="mt-4 flex items-center" aria-hidden="true">
      <span class="h-px w-8 bg-border" />
    </span>
  </div>
</template>

<style scoped>
.hero-stage {
  position: absolute;
  inset-inline: 0;
  bottom: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 2.25rem;
  text-align: center;
}

.type-caret {
  display: inline-block;
  width: 2px;
  height: 0.9em;
  margin-left: 3px;
  vertical-align: -0.08em;
  border-radius: 2px;
  background: var(--brand);
  animation: type-caret-blink 0.9s steps(1) infinite;
}

@keyframes type-caret-blink {
  0%,
  49% {
    opacity: 1;
  }
  50%,
  100% {
    opacity: 0;
  }
}

@media (min-width: 640px) {
  .hero-stage {
    margin-bottom: 2.75rem;
  }
}

@media (max-height: 680px) {
  .hero-stage {
    position: static;
    margin-bottom: 1.5rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .type-caret {
    display: none;
  }
}
</style>
