<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

// 波浪区域：整页画布。深色区域以大幅摆动的有机曲线为边界，
// 网格线条与填充都裁剪在区域内部，品牌色只描曲线本身。
const rootEl = ref<HTMLDivElement | null>(null)
const canvasEl = ref<HTMLCanvasElement | null>(null)
const panelProbe = ref<HTMLSpanElement | null>(null)

// 边界曲线控制点（页面宽高比例）。区域覆盖页面宽度的 61.5%~69%，
// 极值点切线均为垂直方向，保证曲线圆滑无尖角。
const CURVE_START_X = 0.65
const CURVE_SEGMENTS = [
  [0.665, 0.1, 0.69, 0.22, 0.69, 0.3],
  [0.69, 0.4, 0.615, 0.6, 0.615, 0.72],
  [0.615, 0.84, 0.685, 0.88, 0.685, 1],
] as const
const GRID_SPACING = 26

let ctx: CanvasRenderingContext2D | null = null
let observer: ResizeObserver | undefined
let themeObserver: MutationObserver | undefined
let resizeTimer: number | undefined

function probeColor(el: HTMLElement | null): string {
  return el ? getComputedStyle(el).color : '#000000'
}

function buildBoundaryPath(canvas: CanvasRenderingContext2D, width: number, height: number): void {
  canvas.moveTo(CURVE_START_X * width, 0)
  for (const [c1x, c1y, c2x, c2y, ex, ey] of CURVE_SEGMENTS) {
    canvas.bezierCurveTo(c1x * width, c1y * height, c2x * width, c2y * height, ex * width, ey * height)
  }
}

function draw(): void {
  if (!ctx || !canvasEl.value || !rootEl.value) return

  const rect = rootEl.value.getBoundingClientRect()
  const width = rect.width
  const height = rect.height
  if (width < 40 || height < 40) return

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvasEl.value.width = Math.round(width * dpr)
  canvasEl.value.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const panel = probeColor(panelProbe.value)
  const fg = getComputedStyle(rootEl.value).color

  ctx.clearRect(0, 0, width, height)

  // 波浪区域：填充 + 裁剪在区域内部的网格线
  ctx.save()
  ctx.beginPath()
  buildBoundaryPath(ctx, width, height)
  ctx.lineTo(0, height)
  ctx.lineTo(0, 0)
  ctx.closePath()
  ctx.clip()

  ctx.fillStyle = panel
  ctx.fillRect(0, 0, width, height)

  ctx.strokeStyle = fg
  ctx.globalAlpha = 0.08
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let x = GRID_SPACING; x < width; x += GRID_SPACING) {
    ctx.moveTo(x + 0.5, 0)
    ctx.lineTo(x + 0.5, height)
  }
  for (let y = GRID_SPACING; y < height; y += GRID_SPACING) {
    ctx.moveTo(0, y + 0.5)
    ctx.lineTo(width, y + 0.5)
  }
  ctx.stroke()
  ctx.globalAlpha = 1
  ctx.restore()

  // 中性描边：只勾波浪曲线本身
  ctx.beginPath()
  buildBoundaryPath(ctx, width, height)
  ctx.strokeStyle = fg
  ctx.globalAlpha = 0.25
  ctx.lineWidth = 1.5
  ctx.stroke()
  ctx.globalAlpha = 1
}

function onResize(): void {
  window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(draw, 140)
}

onMounted(() => {
  if (!rootEl.value || !canvasEl.value) return
  ctx = canvasEl.value.getContext('2d')
  if (!ctx) return

  draw()

  observer = new ResizeObserver(onResize)
  observer.observe(rootEl.value)
  themeObserver = new MutationObserver(() => draw())
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] })
})

onBeforeUnmount(() => {
  window.clearTimeout(resizeTimer)
  observer?.disconnect()
  themeObserver?.disconnect()
})
</script>

<template>
  <div
    ref="rootEl"
    class="wave-scene text-foreground"
    aria-hidden="true"
  >
    <canvas ref="canvasEl"></canvas>
    <span
      ref="panelProbe"
      class="pointer-events-none absolute opacity-0"
      style="color: var(--panel, var(--sidebar))"
    ></span>
  </div>
</template>

<style scoped>
.wave-scene {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.wave-scene canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
