<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import BrandMark from '@/components/brand/BrandMark.vue'
import { Button } from '@/components/ui/button'
import type { ErrorActionKind } from '@/lib/errorPages'
import { resolveErrorPage } from '@/lib/errorPages'

const props = withDefaults(defineProps<{ code?: string }>(), {
  code: '404',
})

const router = useRouter()
const page = computed(() => resolveErrorPage(props.code))

const driftDots = [
  { x: 3, y: -15, size: 5.5, opacity: 0.58 },
  { x: 17, y: 9, size: 4.5, opacity: 0.5 },
  { x: 34, y: -8, size: 3.6, opacity: 0.4 },
  { x: 52, y: 12, size: 2.8, opacity: 0.32 },
  { x: 70, y: -4, size: 2.2, opacity: 0.23 },
  { x: 88, y: 10, size: 1.6, opacity: 0.16 },
]

function runAction(kind: ErrorActionKind): void {
  if (kind === 'home') {
    void router.push('/')
  } else if (window.history.length > 1) {
    router.back()
  } else {
    void router.push('/')
  }
}
</script>

<template>
  <div class="console-surface flex min-h-dvh flex-col bg-background text-foreground">
    <header class="mx-auto flex w-full max-w-[1120px] items-center px-6 py-5 sm:px-10 sm:py-7">
      <RouterLink
        to="/"
        class="inline-flex items-center gap-2.5 rounded-md text-sm font-semibold text-foreground transition-opacity hover:opacity-70 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        aria-label="Back to PigeonAgent workspace"
      >
        <BrandMark size="sm" />
        PigeonAgent
      </RouterLink>
    </header>

    <main class="mx-auto flex w-full max-w-[1120px] flex-1 flex-col items-center justify-center px-6 pb-16 text-center sm:px-10 sm:pb-24">
      <p class="sr-only">{{ page.code }} {{ page.reason }}：{{ page.title }}</p>

      <div class="route-stage" aria-hidden="true">
        <span class="route-grid" />

        <span class="route-line route-line--in" />
        <span
          v-if="page.variant !== 'lost'"
          class="route-line route-line--out"
          :class="{ 'is-stopped': page.variant !== 'broken' }"
        />
        <span v-else class="route-drift">
          <span
            v-for="(dot, index) in driftDots"
            :key="index"
            class="route-dot"
            :style="{
              left: `${dot.x}%`,
              '--dot-y': `${dot.y}px`,
              width: `${dot.size}px`,
              height: `${dot.size}px`,
              opacity: dot.opacity,
            }"
          />
        </span>

        <span v-if="page.variant === 'unauthorized'" class="route-mark">
          <svg viewBox="0 0 36 36" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="5.5" />
            <path d="M15 15 30 30" />
            <path d="M24 24l3.5-3.5M28 28l3.5-3.5" />
          </svg>
        </span>
        <span v-else-if="page.variant === 'forbidden'" class="route-mark">
          <svg viewBox="0 0 40 36" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <path d="M6 8l10 24M16 8l10 24M26 8l10 24" />
          </svg>
        </span>
        <span v-else-if="page.variant === 'broken'" class="route-mark">
          <svg viewBox="0 0 46 36" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 18 12 4 20 30 28 7 36 26 44 16" />
          </svg>
        </span>
        <span v-else-if="page.variant === 'paused'" class="route-mark">
          <svg viewBox="0 0 36 36" fill="currentColor">
            <rect x="9" y="7" width="6" height="22" rx="3" />
            <rect x="21" y="7" width="6" height="22" rx="3" />
          </svg>
        </span>

        <div class="station">
          <span class="station-tick station-tick--n" />
          <span class="station-tick station-tick--e" />
          <span class="station-tick station-tick--s" />
          <span class="station-tick station-tick--w" />
          <span class="station-code font-title">{{ page.code }}</span>
        </div>
      </div>

      <section class="mt-6 w-full sm:mt-8">
        <div class="mx-auto max-w-[520px]">
          <h1 class="font-title text-[26px] leading-[1.4] text-balance text-foreground sm:text-[32px]">
            {{ page.title }}
          </h1>
          <p class="mx-auto mt-3 max-w-[46ch] text-sm leading-7 text-pretty text-muted-foreground">
            {{ page.description }}
          </p>
          <div class="mt-7 flex flex-wrap items-center justify-center gap-2.5">
            <Button
              v-for="action in page.actions"
              :key="action.kind"
              :variant="action.variant ?? 'default'"
              class="h-9 px-4"
              @click="runAction(action.kind)"
            >
              {{ action.label }}
            </Button>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.route-stage {
  --station-x: 50%;
  --station-r: clamp(68px, 9vw, 98px);
  --mark-gap: 20px;
  position: relative;
  height: clamp(180px, 26vh, 240px);
}

.route-grid {
  position: absolute;
  inset: -10px 0;
  background-image: radial-gradient(
    circle,
    color-mix(in srgb, var(--foreground) 16%, transparent) 1px,
    transparent 1.2px
  );
  background-size: 22px 22px;
  opacity: 0.34;
  pointer-events: none;
  mask-image: radial-gradient(ellipse 44% 120% at 50% 50%, #000 6%, transparent 72%);
  -webkit-mask-image: radial-gradient(ellipse 44% 120% at 50% 50%, #000 6%, transparent 72%);
}

.route-line {
  position: absolute;
  top: 50%;
  height: 1px;
  background-image: repeating-linear-gradient(
    90deg,
    color-mix(in srgb, var(--foreground) 52%, transparent) 0 2px,
    transparent 2px 10px
  );
  transform: translateY(-50%);
  animation: route-draw 1100ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.route-line--in {
  left: 0;
  width: var(--station-x);
  animation-delay: 80ms;
}

.route-line--out {
  left: var(--station-x);
  right: 0;
  animation-delay: 180ms;
}

.route-line--out.is-stopped {
  right: auto;
  width: calc(var(--station-r) + var(--mark-gap) + 8px);
}

.route-mark {
  position: absolute;
  top: 50%;
  left: calc(var(--station-x) + var(--station-r) + var(--mark-gap));
  display: grid;
  width: clamp(30px, 4vw, 44px);
  padding: 4px;
  color: var(--brand);
  background: var(--background);
  transform: translateY(-50%);
}

.route-mark svg {
  width: 100%;
  height: auto;
}

.route-drift {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: calc(var(--station-x) + var(--station-r) + 4px);
  animation: drift-in 700ms ease-out 340ms both;
}

.route-dot {
  position: absolute;
  top: calc(50% + var(--dot-y));
  border-radius: 9999px;
  background: var(--foreground);
  transform: translate(-50%, -50%);
}

.station {
  position: absolute;
  top: 50%;
  left: var(--station-x);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: calc(var(--station-r) * 2);
  height: calc(var(--station-r) * 2);
  border: 1px solid color-mix(in srgb, var(--foreground) 18%, transparent);
  border-radius: 9999px;
  background: var(--background);
  transform: translate(-50%, -50%);
  animation: station-in 700ms cubic-bezier(0.22, 1, 0.36, 1) 260ms both;
}

.station-code {
  font-size: clamp(42px, 5.2vw, 68px);
  line-height: 1;
  letter-spacing: 0.01em;
}

.station-tick {
  position: absolute;
  background: var(--brand);
  opacity: 0.85;
}

.station-tick--n {
  top: -14px;
  left: 50%;
  width: 1px;
  height: 8px;
  margin-left: -0.5px;
}

.station-tick--s {
  bottom: -14px;
  left: 50%;
  width: 1px;
  height: 8px;
  margin-left: -0.5px;
}

.station-tick--e {
  top: 50%;
  right: -14px;
  width: 8px;
  height: 1px;
  margin-top: -0.5px;
}

.station-tick--w {
  top: 50%;
  left: -14px;
  width: 8px;
  height: 1px;
  margin-top: -0.5px;
}

@keyframes route-draw {
  from {
    clip-path: inset(0 100% 0 0);
  }
  to {
    clip-path: inset(0 0 0 0);
  }
}

@keyframes station-in {
  from {
    opacity: 0;
    transform: translate(-50%, -46%) scale(0.94);
  }
  to {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }
}

@keyframes drift-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .route-line,
  .route-drift,
  .station {
    animation: none;
  }
}
</style>
