<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

// 信号网格：在波浪面板的网格交点上铺一层稀疏点阵，几个信标节点按各自的
// 周期向外发信，扫描环经过的格点被点亮成品牌色；其余格点保持极低对比，
// 不跟中央的像素字标抢注意力。鼠标靠近时格点会轻微提亮，作为指向反馈。

interface Rgb {
  r: number
  g: number
  b: number
}

interface Dot {
  x: number
  y: number
}

interface SignalNode {
  x: number
  y: number
  period: number
  phase: number
}

interface Ring {
  x: number
  y: number
  radius: number
  band: number
  strength: number
}

const TAU = Math.PI * 2

// ============================================================
// 可调参数：点阵、信标与扫描环
// ============================================================
// 点阵间距：与 WaveScene 的网格（26px）对齐，取两格一个点
const DOT_SPACING = 52
const DOT_RADIUS = 1.05
const BASE_ALPHA_DARK = 0.17
const BASE_ALPHA_LIGHT = 0.14
// 扫描环存活时间占周期的比例，以及环的最大半径（相对短边）
const RING_SPAN = 0.62
const RING_MAX_SCALE = 0.62
const RING_ALPHA = 0.9
// 鼠标附近的提亮范围与强度
const POINTER_RADIUS = 130
const POINTER_STRENGTH = 0.4
// 右侧淡出：波浪边界之外没有面板底色，点阵要提前收住
const EDGE_FADE_START = 0.82
const EDGE_FADE_END = 0.95

// 信标：x/y 为画布占比，period 为发信周期（毫秒），phase 为初始相位
const NODE_DEFS = [
  { x: 0.18, y: 0.26, period: 6400, phase: 0 },
  { x: 0.74, y: 0.72, period: 7800, phase: 0.3 },
  { x: 0.33, y: 0.8, period: 8800, phase: 0.58 },
]

const rootElRef = ref<HTMLDivElement | null>(null)
const canvasElRef = ref<HTMLCanvasElement | null>(null)
const fgProbeRef = ref<HTMLSpanElement | null>(null)
const brandProbeRef = ref<HTMLSpanElement | null>(null)

let rootEl: HTMLDivElement | null = null
let canvasEl: HTMLCanvasElement | null = null
let ctx: CanvasRenderingContext2D | null = null
let observer: ResizeObserver | undefined
let themeObserver: MutationObserver | undefined
let intersection: IntersectionObserver | undefined
let rafId = 0
let resizeTimer: number | undefined
let disposed = false
let running = false
let lastTime = 0
let elapsed = 1600
let width = 0
let height = 0
let dpr = 1
let dots: Dot[] = []
let nodes: SignalNode[] = []
let fg: Rgb = { r: 236, g: 236, b: 236 }
let brand: Rgb = { r: 126, g: 166, b: 201 }
let isDark = true
let pointerX = 0
let pointerY = 0
let pointerStrength = 0
let pointerTarget = 0

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function parseColor(value: string): Rgb {
  const rgb = value.match(/rgba?\(([^)]+)\)/i)
  if (rgb) {
    const parts = rgb[1].split(',').map((part) => Number.parseFloat(part))
    return { r: parts[0] || 0, g: parts[1] || 0, b: parts[2] || 0 }
  }
  const hex = value.trim().replace('#', '')
  const full = hex.length === 3 ? hex.split('').map((ch) => ch + ch).join('') : hex
  const num = Number.parseInt(full.slice(0, 6), 16)
  if (!Number.isFinite(num)) return { r: 200, g: 200, b: 200 }
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 }
}

function rgba(color: Rgb, alpha: number): string {
  return `rgba(${Math.round(color.r)}, ${Math.round(color.g)}, ${Math.round(color.b)}, ${clamp01(alpha).toFixed(3)})`
}

function mix(from: Rgb, to: Rgb, amount: number): Rgb {
  const t = clamp01(amount)
  return {
    r: from.r + (to.r - from.r) * t,
    g: from.g + (to.g - from.g) * t,
    b: from.b + (to.b - from.b) * t,
  }
}

function resolveColors(): void {
  if (!rootEl) return
  fg = fgProbeRef.value ? parseColor(getComputedStyle(fgProbeRef.value).color) : fg
  brand = brandProbeRef.value ? parseColor(getComputedStyle(brandProbeRef.value).color) : brand
  isDark = document.documentElement.classList.contains('dark')
}

function buildDots(): void {
  dots = []
  for (let y = DOT_SPACING; y < height; y += DOT_SPACING) {
    for (let x = DOT_SPACING; x < width; x += DOT_SPACING) {
      dots.push({ x, y })
    }
  }
  nodes = NODE_DEFS.map((node) => ({
    x: node.x * width,
    y: node.y * height,
    period: node.period,
    phase: node.phase,
  }))
}

function edgeFade(x: number): number {
  const start = width * EDGE_FADE_START
  const end = width * EDGE_FADE_END
  if (x <= start) return 1
  if (x >= end) return 0
  return 1 - (x - start) / (end - start)
}

function drawBaseDots(): void {
  if (!ctx) return
  const radius = DOT_RADIUS
  ctx.fillStyle = rgba(fg, isDark ? BASE_ALPHA_DARK : BASE_ALPHA_LIGHT)
  ctx.beginPath()
  for (const dot of dots) {
    if (edgeFade(dot.x) <= 0) continue
    ctx.moveTo(dot.x + radius, dot.y)
    ctx.arc(dot.x, dot.y, radius, 0, TAU)
  }
  ctx.fill()
}

function collectRings(): Ring[] {
  const maxRadius = Math.min(width, height) * RING_MAX_SCALE
  const rings: Ring[] = []
  if (!ctx) return rings

  for (const node of nodes) {
    const local = ((elapsed / node.period) + node.phase) % 1
    if (local >= RING_SPAN) continue
    const progress = local / RING_SPAN
    const radius = progress * maxRadius
    const fade = Math.pow(1 - progress, 1.5)
    rings.push({
      x: node.x,
      y: node.y,
      radius,
      band: Math.max(9, radius * 0.07 + 8),
      strength: fade * RING_ALPHA,
    })

    ctx.save()
    ctx.setLineDash([2, 7])
    ctx.lineWidth = 1
    ctx.strokeStyle = rgba(brand, fade * 0.1)
    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, TAU)
    ctx.stroke()
    ctx.restore()
  }
  return rings
}

function drawNodes(): void {
  if (!ctx) return
  for (const node of nodes) {
    const local = ((elapsed / node.period) + node.phase) % 1
    const flare = local < 0.12 ? 1 - local / 0.12 : 0

    ctx.strokeStyle = rgba(brand, 0.28 + flare * 0.45)
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(node.x, node.y, 5.5, 0, TAU)
    ctx.stroke()

    ctx.beginPath()
    ctx.moveTo(node.x - 9, node.y)
    ctx.lineTo(node.x - 6.5, node.y)
    ctx.moveTo(node.x + 6.5, node.y)
    ctx.lineTo(node.x + 9, node.y)
    ctx.moveTo(node.x, node.y - 9)
    ctx.lineTo(node.x, node.y - 6.5)
    ctx.moveTo(node.x, node.y + 6.5)
    ctx.lineTo(node.x, node.y + 9)
    ctx.stroke()

    ctx.fillStyle = rgba(brand, 0.7 + flare * 0.3)
    ctx.beginPath()
    ctx.arc(node.x, node.y, 1.4, 0, TAU)
    ctx.fill()
  }
}

function drawHighlights(rings: Ring[]): void {
  if (!ctx) return
  const baseAlpha = isDark ? BASE_ALPHA_DARK : BASE_ALPHA_LIGHT
  const hasPointer = pointerStrength > 0.01

  for (const dot of dots) {
    const fade = edgeFade(dot.x)
    if (fade <= 0) continue

    let glow = 0
    for (const ring of rings) {
      const dist = Math.hypot(dot.x - ring.x, dot.y - ring.y)
      const delta = Math.abs(dist - ring.radius)
      if (delta < ring.band) {
        const weight = 1 - delta / ring.band
        glow += weight * weight * ring.strength
      }
      if (dist < 56) glow += (1 - dist / 56) * 0.16 * ring.strength
    }

    let cursorGlow = 0
    if (hasPointer) {
      const dist = Math.hypot(dot.x - pointerX, dot.y - pointerY)
      if (dist < POINTER_RADIUS) {
        const weight = 1 - dist / POINTER_RADIUS
        cursorGlow = weight * weight * POINTER_STRENGTH * pointerStrength
      }
    }

    const intensity = Math.min(1, glow + cursorGlow)
    if (intensity < 0.03) continue

    const color = mix(fg, brand, Math.min(1, intensity * 1.5))
    ctx.fillStyle = rgba(color, Math.min(0.9, baseAlpha + intensity * 0.62) * fade)
    ctx.beginPath()
    ctx.arc(dot.x, dot.y, DOT_RADIUS + intensity * 1.5, 0, TAU)
    ctx.fill()
  }
}

function renderFrame(): void {
  if (!ctx || width < 60 || height < 60) return
  ctx.clearRect(0, 0, width, height)
  drawBaseDots()
  const rings = collectRings()
  drawNodes()
  drawHighlights(rings)
}

function step(now: number): void {
  const dt = lastTime === 0 ? 16.7 : Math.min(50, now - lastTime)
  lastTime = now
  elapsed += dt

  const ease = 1 - Math.pow(1 - 0.12, dt / 16.7)
  pointerStrength += (pointerTarget - pointerStrength) * ease

  renderFrame()
}

function loop(now: number): void {
  if (disposed) return
  step(now)
  rafId = requestAnimationFrame(loop)
}

function startLoop(): void {
  if (disposed || reduced || running) return
  running = true
  lastTime = 0
  rafId = requestAnimationFrame(loop)
}

function stopLoop(): void {
  running = false
  cancelAnimationFrame(rafId)
}

function layout(): void {
  if (!rootEl || !canvasEl || !ctx) return

  const rect = rootEl.getBoundingClientRect()
  if (rect.width < 60 || rect.height < 60) return

  width = rect.width
  height = rect.height
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvasEl.width = Math.round(width * dpr)
  canvasEl.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  buildDots()
  if (reduced) renderFrame()
}

function onResize(): void {
  window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => {
    layout()
    if (!reduced) lastTime = 0
  }, 140)
}

function onPointerMove(event: PointerEvent): void {
  if (!rootEl) return
  const rect = rootEl.getBoundingClientRect()
  pointerX = event.clientX - rect.left
  pointerY = event.clientY - rect.top
  pointerTarget = 1
}

function onPointerLeave(): void {
  pointerTarget = 0
}

onMounted(() => {
  rootEl = rootElRef.value
  canvasEl = canvasElRef.value
  if (!rootEl || !canvasEl) return
  ctx = canvasEl.getContext('2d')
  if (!ctx) return

  resolveColors()
  layout()

  observer = new ResizeObserver(onResize)
  observer.observe(rootEl)

  themeObserver = new MutationObserver(() => {
    resolveColors()
    if (!running) renderFrame()
  })
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })

  intersection = new IntersectionObserver((entries) => {
    const entry = entries[0]
    if (entry?.isIntersecting) startLoop()
    else stopLoop()
  })
  intersection.observe(rootEl)

  window.addEventListener('pointermove', onPointerMove, { passive: true })
  window.addEventListener('pointerleave', onPointerLeave)

  if (reduced) renderFrame()
  else startLoop()
})

onBeforeUnmount(() => {
  disposed = true
  stopLoop()
  window.clearTimeout(resizeTimer)
  observer?.disconnect()
  themeObserver?.disconnect()
  intersection?.disconnect()
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerleave', onPointerLeave)
})
</script>

<template>
  <div ref="rootElRef" class="signal-field" aria-hidden="true">
    <canvas ref="canvasElRef"></canvas>
    <span ref="fgProbeRef" class="signal-field__probe" style="color: var(--foreground)"></span>
    <span ref="brandProbeRef" class="signal-field__probe" style="color: var(--brand)"></span>
  </div>
</template>

<style scoped>
.signal-field {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  color: var(--foreground);
}

.signal-field canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.signal-field__probe {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
</style>
