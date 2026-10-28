<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

/** 点阵间距、指针影响半径、最大位移：和静态稿 mock 里的 A 方案一致。 */
const PITCH = 24;
const RADIUS = 110;
const SHIFT = 15;

const canvas = ref<HTMLCanvasElement | null>(null);

let context: CanvasRenderingContext2D | null = null;
let observer: ResizeObserver | null = null;
let frame = 0;
let box = { left: 0, top: 0, width: 0, height: 0 };
let ink = "#0d0d0d";
let accent = "#256d85";
let clearances: { x0: number; y0: number; x1: number; y1: number }[] = [];
const pointer = { x: 0, y: 0, active: false };

/** 没有 hover（触屏）或系统要求减少动效时，只画静止点阵，一帧都不跑。 */
const reactive = () =>
  !window.matchMedia("(hover: none)").matches &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function readTokens() {
  const style = getComputedStyle(document.documentElement);
  ink = style.getPropertyValue("--ink").trim() || "#0d0d0d";
  accent = style.getPropertyValue("--accent").trim() || ink;
}

function paint() {
  if (!context) return;
  const live = reactive() && pointer.active;
  context.clearRect(0, 0, box.width, box.height);
  for (let y = PITCH / 2; y < box.height; y += PITCH) {
    for (let x = PITCH / 2; x < box.width; x += PITCH) {
      let px = x;
      let py = y;
      let alpha = 0.12;
      let size = 1;
      let lift = 0;
      if (clearances.some((area) => x > area.x0 && x < area.x1 && y > area.y0 && y < area.y1)) {
        alpha = 0.04;
      }
      if (live) {
        const dx = x - pointer.x;
        const dy = y - pointer.y;
        const distance = Math.hypot(dx, dy);
        if (distance < RADIUS) {
          const t = 1 - distance / RADIUS;
          lift = t * t * (3 - 2 * t);
          const inv = 1 / (distance || 1);
          px += dx * inv * lift * SHIFT;
          py += dy * inv * lift * SHIFT;
          alpha += lift * 0.45;
          size += lift * 0.9;
        }
      }
      context.globalAlpha = Math.min(0.62, alpha);
      context.fillStyle = lift > 0.72 ? accent : ink;
      context.beginPath();
      context.arc(px, py, size, 0, Math.PI * 2);
      context.fill();
    }
  }
  context.globalAlpha = 1;
}

function queue() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    paint();
  });
}

function measure() {
  const element = canvas.value;
  if (!element) return;
  const rect = element.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  box = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
  element.width = Math.round(rect.width * dpr);
  element.height = Math.round(rect.height * dpr);
  context = element.getContext("2d");
  if (context) context.setTransform(dpr, 0, 0, dpr, 0, 0);
  // 标了 data-particle-clear 的文字压在读区上，背后的点要淡掉才不影响可读性
  const host = element.parentElement;
  clearances = host
    ? [...host.querySelectorAll<HTMLElement>("[data-particle-clear]")].map((node) => {
        const area = node.getBoundingClientRect();
        return {
          x0: area.left - rect.left - 28,
          y0: area.top - rect.top - 20,
          x1: area.right - rect.left + 28,
          y1: area.bottom - rect.top + 20,
        };
      })
    : [];
  paint();
}

function onMove(event: PointerEvent) {
  const x = event.clientX - box.left;
  const y = event.clientY - box.top;
  pointer.x = x;
  pointer.y = y;
  // 光标落在标题或输入框上时点阵保持安静：指针事件的目标就是最上层那个元素
  const calm = (event.target as Element | null)?.closest?.("[data-particle-clear]");
  pointer.active = !calm && x >= 0 && y >= 0 && x <= box.width && y <= box.height;
  queue();
}

function onLeave() {
  pointer.active = false;
  queue();
}

function onThemeChange() {
  readTokens();
  paint();
}

const dark = window.matchMedia("(prefers-color-scheme: dark)");

onMounted(() => {
  readTokens();
  measure();
  observer = new ResizeObserver(measure);
  if (canvas.value) observer.observe(canvas.value);
  if (reactive()) {
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("blur", onLeave);
  }
  dark.addEventListener("change", onThemeChange);
});

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame);
  observer?.disconnect();
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("blur", onLeave);
  dark.removeEventListener("change", onThemeChange);
});
</script>

<template>
  <canvas ref="canvas" class="pointer-events-none absolute inset-0 size-full" aria-hidden="true" />
</template>
