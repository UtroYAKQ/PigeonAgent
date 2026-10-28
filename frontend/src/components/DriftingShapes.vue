<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

/**
 * 7 个实线空心图形的弹球：走直线、撞边反弹、两两等质量弹性相撞（完全不重叠），
 * 标题区是一块隐形挡板。尺寸档位决定速度和浓度——大的慢而淡、小的快而清。
 */
const SIDES = [0, 3, 4, 6];
const TIERS = [
  { size: [134, 150], speed: [9, 11], alpha: 0.22 },
  { size: [108, 122], speed: [11, 14], alpha: 0.25 },
  { size: [88, 100], speed: [13, 16], alpha: 0.28 },
  { size: [70, 82], speed: [15, 18], alpha: 0.31 },
  { size: [56, 66], speed: [17, 21], alpha: 0.34 },
  { size: [46, 54], speed: [19, 23], alpha: 0.37 },
  { size: [38, 46], speed: [21, 26], alpha: 0.4 },
];
/** 离边缘留这么多像素，图形不被切掉。 */
const INSET = 20;

/** 一种边数一种颜色，明暗各一套；都是低饱和的，白底黑底都压得住。 */
const PALETTE: Record<number, [string, string]> = {
  0: ["#256d85", "#6cc7de"],
  3: ["#5b7a6a", "#8fc0a4"],
  4: ["#9a6a4f", "#d3a184"],
  6: ["#6a5f8f", "#a99ccd"],
};

const canvas = ref<HTMLCanvasElement | null>(null);
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const calm = window.matchMedia("(prefers-reduced-motion: reduce)");

let context: CanvasRenderingContext2D | null = null;
let observer: ResizeObserver | null = null;
let raf = 0;
let last = 0;
let width = 0;
let height = 0;

type Shape = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  sides: number;
  alpha: number;
  angle: number;
  spin: number;
};

let shapes: Shape[] = [];
let keepOut: { x0: number; y0: number; x1: number; y1: number } | null = null;

const between = (min: number, max: number) => min + Math.random() * (max - min);
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

function spawn(sides: number, tier: (typeof TIERS)[number]): Shape {
  const size = between(tier.size[0], tier.size[1]);
  const inset = size / 2 + INSET;
  const direction = between(0, Math.PI * 2);
  const speed = between(tier.speed[0], tier.speed[1]);
  return {
    x: between(inset, Math.max(inset, width - inset)),
    y: between(inset, Math.max(inset, height - inset)),
    vx: Math.cos(direction) * speed,
    vy: Math.sin(direction) * speed,
    size,
    sides,
    alpha: tier.alpha,
    angle: between(0, Math.PI * 2),
    spin: ((Math.random() - 0.5) * 14) / size,
  };
}

/** 每档配一种图形，随机抽可能全是圆。 */
function seed(): void {
  const kinds = [...SIDES].sort(() => Math.random() - 0.5);
  shapes = TIERS.map((tier, index) => spawn(kinds[index % kinds.length], tier));
}

/** 等质量弹性碰撞：交换沿连心线的速度分量，再把两个球挪到刚好相切。 */
function collide(a: Shape, b: Shape): void {
  const limit = (a.size + b.size) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const distance = Math.hypot(dx, dy);
  if (distance >= limit) return;
  const nx = dx / (distance || 1);
  const ny = dy / (distance || 1);
  const along = a.vx * nx + a.vy * ny - (b.vx * nx + b.vy * ny);
  if (along > 0) {
    a.vx -= along * nx;
    a.vy -= along * ny;
    b.vx += along * nx;
    b.vy += along * ny;
  }
  const shift = (limit - distance) / 2;
  a.x -= nx * shift;
  a.y -= ny * shift;
  b.x += nx * shift;
  b.y += ny * shift;
}

/** 标题区当墙用：撞上去按法线弹开。 */
function bounceOffTitle(shape: Shape): void {
  if (!keepOut) return;
  const radius = shape.size / 2;
  const nearestX = clamp(shape.x, keepOut.x0, keepOut.x1);
  const nearestY = clamp(shape.y, keepOut.y0, keepOut.y1);
  const dx = shape.x - nearestX;
  const dy = shape.y - nearestY;
  const distance = Math.hypot(dx, dy);
  if (distance >= radius) return;
  let nx = dx / (distance || 1);
  let ny = dy / (distance || 1);
  if (distance === 0) {
    // 球心掉进矩形里：从最近的一条边退出去
    const left = shape.x - keepOut.x0;
    const right = keepOut.x1 - shape.x;
    const up = shape.y - keepOut.y0;
    const down = keepOut.y1 - shape.y;
    const least = Math.min(left, right, up, down);
    nx = 0;
    ny = 0;
    if (least === up) ny = -1;
    else if (least === down) ny = 1;
    else if (least === left) nx = -1;
    else nx = 1;
    shape.x = nearestX + nx * radius;
    shape.y = nearestY + ny * radius;
  } else {
    shape.x = nearestX + nx * radius;
    shape.y = nearestY + ny * radius;
  }
  const along = shape.vx * nx + shape.vy * ny;
  if (along < 0) {
    shape.vx -= 2 * along * nx;
    shape.vy -= 2 * along * ny;
  }
}

function step(dt: number) {
  for (const shape of shapes) {
    shape.x += shape.vx * dt;
    shape.y += shape.vy * dt;
    shape.angle += shape.spin * dt;
    const inset = shape.size / 2 + INSET;
    if (shape.x < inset) {
      shape.x = inset;
      shape.vx = Math.abs(shape.vx);
    } else if (shape.x > width - inset) {
      shape.x = Math.max(inset, width - inset);
      shape.vx = -Math.abs(shape.vx);
    }
    if (shape.y < inset) {
      shape.y = inset;
      shape.vy = Math.abs(shape.vy);
    } else if (shape.y > height - inset) {
      shape.y = Math.max(inset, height - inset);
      shape.vy = -Math.abs(shape.vy);
    }
    bounceOffTitle(shape);
  }
  // 两两相撞放最后：前面任何位置修正都不该留下一个「叠在一起」的渲染帧
  for (let i = 0; i < shapes.length; i += 1) {
    for (let j = i + 1; j < shapes.length; j += 1) collide(shapes[i], shapes[j]);
  }
}

function outline(shape: Shape) {
  if (!context) return;
  const radius = shape.size / 2;
  const vertex = (turn: number) => {
    const angle = shape.angle + turn * Math.PI * 2 - Math.PI / 2;
    return [shape.x + Math.cos(angle) * radius, shape.y + Math.sin(angle) * radius] as const;
  };
  context.beginPath();
  if (shape.sides === 0) {
    context.arc(shape.x, shape.y, radius, 0, Math.PI * 2);
  } else {
    for (let i = 0; i <= shape.sides; i += 1) {
      const [px, py] = vertex(i / shape.sides);
      if (i === 0) context.moveTo(px, py);
      else context.lineTo(px, py);
    }
  }
  context.strokeStyle = PALETTE[shape.sides][dark.matches ? 1 : 0];
  context.globalAlpha = shape.alpha;
  context.lineWidth = 1.6;
  context.stroke();
  context.globalAlpha = 1;
}

function draw() {
  if (!context) return;
  context.clearRect(0, 0, width, height);
  for (const shape of shapes) outline(shape);
}

function loop(now: number) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  step(dt);
  draw();
  raf = requestAnimationFrame(loop);
}

function start() {
  if (!raf) {
    last = performance.now();
    raf = requestAnimationFrame(loop);
  }
}

function stop() {
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
}

function measure() {
  const element = canvas.value;
  if (!element) return;
  const rect = element.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = rect.width;
  height = rect.height;
  element.width = Math.round(width * dpr);
  element.height = Math.round(height * dpr);
  context = element.getContext("2d");
  if (context) context.setTransform(dpr, 0, 0, dpr, 0, 0);
  const title = element.parentElement?.querySelector<HTMLElement>('[data-particle-clear]');
  if (title) {
    const area = title.getBoundingClientRect();
    const pad = 26;
    keepOut = {
      x0: area.left - rect.left - pad,
      y0: area.top - rect.top - pad,
      x1: area.right - rect.left + pad,
      y1: area.bottom - rect.top + pad,
    };
  } else {
    keepOut = null;
  }
  if (shapes.length === 0) seed();
  for (const shape of shapes) {
    const inset = shape.size / 2 + INSET;
    shape.x = clamp(shape.x, inset, Math.max(inset, width - inset));
    shape.y = clamp(shape.y, inset, Math.max(inset, height - inset));
  }
  draw();
}

function onVisibility() {
  if (document.hidden) stop();
  else start();
}

onMounted(() => {
  measure();
  observer = new ResizeObserver(measure);
  if (canvas.value) observer.observe(canvas.value);
  if (!calm.matches) start();
  document.addEventListener("visibilitychange", onVisibility);
  dark.addEventListener("change", draw);
});

onBeforeUnmount(() => {
  stop();
  observer?.disconnect();
  document.removeEventListener("visibilitychange", onVisibility);
  dark.removeEventListener("change", draw);
});
</script>

<template>
  <canvas ref="canvas" class="pointer-events-none absolute inset-0 size-full" aria-hidden="true" />
</template>
