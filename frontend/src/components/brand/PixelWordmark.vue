<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    text?: string
  }>(),
  {
    text: 'PIGEONAGENT',
  },
)

// ============================================================
// 可调参数：想微调像素字样，改下面这一组常量即可
// ============================================================
// 采样字号：越大笔画越粗、越不容易断线
const FONT_PX = 12
// 字符间距（采样像素）：避免低分辨率采样时相邻字母黏连
const CHAR_GAP = 4
// 采样步长：2 表示每 2×2 像素合并成一个块
const SAMPLE_STEP = 1
// 亮点判定阈值（0-255）：越低笔画越粗、字越饱满
const ON_THRESHOLD = 32
// 像素块尺寸范围（CSS 像素）：调小 = 块更小更细腻，整体也会变小
const PIXEL_MIN = 4
const PIXEL_MAX = 8
// 光效：模糊半径与强度（0 = 关闭；强度有效范围 0~1）
const GLOW_BLUR = 0.3
const GLOW_ALPHA = 0.5
// 光晕亮度叠加次数（1~3）：越大光晕越亮
const GLOW_PASSES = 0
// 字块亮度（有效范围 0~1）：调低让光晕更突出
const LETTER_ALPHA = 0.42
// 阴影：向右下偏移的距离（0 = 关闭）
const SHADOW_OFFSET = 1
// 鼠标视差幅度（像素）：字样随鼠标偏移的最大距离
const PARALLAX_X = 30
const PARALLAX_Y = 20
// 视差缓动：每 16.7ms 向目标靠近的比例，越小跟随越柔缓
const PARALLAX_EASE = 0.028
// 光扫：周期（毫秒）、亮度（有效范围 0~1）、光带宽度占画布比例
const SWEEP_PERIOD = 10000
const SWEEP_ALPHA = 1
const SWEEP_WIDTH = 0.1

const rootElRef = ref<HTMLDivElement | null>(null)
const canvasElRef = ref<HTMLCanvasElement | null>(null)

interface Block {
  x: number
  y: number
}

let rootEl: HTMLDivElement | null = null
let canvasEl: HTMLCanvasElement | null = null
let ctx: CanvasRenderingContext2D | null = null
let offCtx: CanvasRenderingContext2D | null = null
let offscreen: HTMLCanvasElement | null = null
let maskCtx: CanvasRenderingContext2D | null = null
let maskCanvas: HTMLCanvasElement | null = null
let sweepCtx: CanvasRenderingContext2D | null = null
let sweepCanvas: HTMLCanvasElement | null = null
let blocks: Block[] = []
let blockPx = 5
let dpr = 1
let observer: ResizeObserver | undefined
let rafId = 0
let disposed = false
let lastTime = 0
let elapsed = 0
let colorRefreshAt = 0
let fgColor = '#ececec'
let offX = 0
let offY = 0
let resizeTimer: number | undefined
const pointer = { x: 0, y: 0, active: false }

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

function resolveColors(): void {
  if (!rootEl) return
  fgColor = getComputedStyle(rootEl).color
}

// 文本低分辨率采样：逐字符绘制（字符间留显式空隙），按 SAMPLE_STEP 合并为块
function sampleGrid(): { cols: number; rows: number; grid: boolean[] } | null {
  const font = `700 ${FONT_PX}px ui-monospace, Menlo, Consolas, monospace`
  const measure = document.createElement('canvas')
  const measureCtx = measure.getContext('2d')
  if (!measureCtx) return null

  measureCtx.font = font
  const chars = [...props.text.toUpperCase()]
  const advances = chars.map((ch) => measureCtx.measureText(ch).width)
  const hiCols = Math.ceil(advances.reduce((sum, w) => sum + w, 0) + CHAR_GAP * (chars.length - 1)) + 2
  const hiRows = FONT_PX + 4

  measure.width = hiCols
  measure.height = hiRows
  const ctx2 = measure.getContext('2d')
  if (!ctx2) return null

  ctx2.font = font
  ctx2.textBaseline = 'top'
  ctx2.fillStyle = '#000'
  let cursor = 1
  chars.forEach((ch, index) => {
    ctx2.fillText(ch, cursor, 2)
    cursor += advances[index] + CHAR_GAP
  })

  const data = ctx2.getImageData(0, 0, hiCols, hiRows).data
  const cols = Math.ceil(hiCols / SAMPLE_STEP)
  const rows = Math.ceil(hiRows / SAMPLE_STEP)
  const grid: boolean[] = new Array(cols * rows).fill(false)

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      let lit = 0
      for (let dy = 0; dy < SAMPLE_STEP; dy += 1) {
        for (let dx = 0; dx < SAMPLE_STEP; dx += 1) {
          const hiRow = row * SAMPLE_STEP + dy
          const hiCol = col * SAMPLE_STEP + dx
          if (hiRow >= hiRows || hiCol >= hiCols) continue
          if (data[(hiRow * hiCols + hiCol) * 4 + 3] > ON_THRESHOLD) lit += 1
        }
      }
      grid[row * cols + col] = lit >= 1
    }
  }
  return { cols, rows, grid }
}

// 块渲染到离屏画布：阴影层 → 本体 + 光晕。视差移动只平移离屏画布
function renderOffscreen(): void {
  if (!offCtx || !offscreen) return

  offCtx.clearRect(0, 0, offscreen.width, offscreen.height)

  const shadowOffsetPx = Math.round(SHADOW_OFFSET * dpr)
  if (SHADOW_OFFSET > 0) {
    offCtx.fillStyle = 'rgba(0, 0, 0, 0.45)'
    for (const b of blocks) {
      offCtx.fillRect(b.x + shadowOffsetPx, b.y + shadowOffsetPx, blockPx, blockPx)
    }
  }

  if (GLOW_BLUR > 0 && GLOW_ALPHA > 0) {
    // 光晕层：强度只作用于光晕；叠加多次可调出比上限更亮的效果
    offCtx.save()
    offCtx.shadowColor = fgColor
    offCtx.shadowBlur = GLOW_BLUR * dpr
    const glowScale = document.documentElement.classList.contains("dark") ? 0.55 : 1
    offCtx.globalAlpha = Math.min(1, GLOW_ALPHA * glowScale)
    offCtx.fillStyle = fgColor
    const passes = Math.max(1, Math.round(GLOW_PASSES))
    for (let p = 0; p < passes; p += 1) {
      for (const b of blocks) {
        offCtx.fillRect(b.x, b.y, blockPx, blockPx)
      }
    }
    offCtx.restore()
  }

  // 字块层：按字块亮度绘制，让光晕更突出
  offCtx.fillStyle = fgColor
  offCtx.globalAlpha = Math.min(1, Math.max(0, LETTER_ALPHA))
  for (const b of blocks) {
    offCtx.fillRect(b.x, b.y, blockPx, blockPx)
  }
}

function layout(): void {
  if (!rootEl || !canvasEl || !ctx) return

  const rect = rootEl.getBoundingClientRect()
  const width = rect.width
  const height = rect.height
  if (width < 40 || height < 20) return

  dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvasEl.width = Math.round(width * dpr)
  canvasEl.height = Math.round(height * dpr)
  ctx.setTransform(1, 0, 0, 1, 0, 0)

  const sampled = sampleGrid()
  if (!sampled) return

  const cell = Math.max(
    PIXEL_MIN,
    Math.min(PIXEL_MAX, Math.floor((width - 4) / sampled.cols), Math.floor((height - 8) / sampled.rows)),
  )
  const gridW = sampled.cols * cell
  const gridH = sampled.rows * cell
  const originX = Math.round(((width - gridW) / 2) * dpr)
  const originY = Math.round(((height - gridH) / 2) * dpr)
  blockPx = Math.max(1, Math.round(cell * dpr) - Math.max(1, Math.round(dpr)))

  blocks = []
  for (let row = 0; row < sampled.rows; row += 1) {
    for (let col = 0; col < sampled.cols; col += 1) {
      if (!sampled.grid[row * sampled.cols + col]) continue
      blocks.push({
        x: originX + col * Math.round(cell * dpr),
        y: originY + row * Math.round(cell * dpr),
      })
    }
  }

  // 离屏画布与主画布同尺寸，视差移动时直接整体平移
  if (!offscreen) {
    offscreen = document.createElement('canvas')
    offCtx = offscreen.getContext('2d')
  }
  offscreen.width = canvasEl.width
  offscreen.height = canvasEl.height
  offCtx?.setTransform(1, 0, 0, 1, 0, 0)
  renderOffscreen()

  // 字母遮罩：亮度固定为 1，供光扫提亮时突破字块本身的不透明度
  if (!maskCanvas) {
    maskCanvas = document.createElement('canvas')
    maskCtx = maskCanvas.getContext('2d')
  }
  maskCanvas.width = canvasEl.width
  maskCanvas.height = canvasEl.height
  if (maskCtx) {
    maskCtx.fillStyle = '#ffffff'
    for (const b of blocks) {
      maskCtx.fillRect(b.x, b.y, blockPx, blockPx)
    }
  }

  // 光扫合成层：同一尺寸，每帧只更新渐变
  if (!sweepCanvas) {
    sweepCanvas = document.createElement('canvas')
    sweepCtx = sweepCanvas.getContext('2d')
  }
  sweepCanvas.width = canvasEl.width
  sweepCanvas.height = canvasEl.height
}

function step(now: number): void {
  if (!ctx || !canvasEl || !offscreen || !rootEl) return

  // 时间差归一化：缓动与动画速度不随刷新率变化；切回标签页时最多按 50ms 计
  const dt = lastTime === 0 ? 16.7 : Math.min(50, now - lastTime)
  lastTime = now
  elapsed += dt

  if (elapsed - colorRefreshAt > 1300) {
    colorRefreshAt = elapsed
    resolveColors()
    renderOffscreen()
  }

  const rect = rootEl.getBoundingClientRect()
  const halfW = Math.max(rect.width / 2, 1)
  const halfH = Math.max(rect.height / 2, 1)
  const nx = pointer.active ? Math.max(-1, Math.min(1, (pointer.x - halfW) / halfW)) : 0
  const ny = pointer.active ? Math.max(-1, Math.min(1, (pointer.y - halfH) / halfH)) : 0

  const ease = 1 - Math.pow(1 - PARALLAX_EASE, dt / 16.7)
  offX += (nx * PARALLAX_X - offX) * ease
  offY += (ny * PARALLAX_Y - offY) * ease

  const idleX = Math.sin(elapsed * 0.0003) * 1.5
  const idleY = Math.cos(elapsed * 0.00039) * 1.2

  const shiftX = Math.round((offX + idleX) * dpr)
  const shiftY = Math.round((offY + idleY) * dpr)

  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height)
  ctx.drawImage(offscreen, shiftX, shiftY)

  // 光扫：亮带周期性扫过，只点亮扫到的字母像素，背景不变。
  // 用全亮字母遮罩合成渐变，不受字块本身 0.42 不透明度的限制，深色主题下也能明显变亮。
  if (SWEEP_ALPHA > 0 && !reduced && sweepCtx && sweepCanvas && maskCanvas) {
    const sweepPhase = elapsed % SWEEP_PERIOD
    const sweepSpan = SWEEP_PERIOD * 0.38
    if (sweepPhase < sweepSpan) {
      const progress = sweepPhase / sweepSpan
      const band = canvasEl.width * SWEEP_WIDTH
      const x = -band + progress * (canvasEl.width + band * 2)
      const gradient = sweepCtx.createLinearGradient(x - band / 2, 0, x + band / 2, canvasEl.height * 0.35)
      gradient.addColorStop(0, 'rgba(255, 255, 255, 0)')
      gradient.addColorStop(0.5, `rgba(255, 255, 255, ${Math.min(1, SWEEP_ALPHA)})`)
      gradient.addColorStop(1, 'rgba(255, 255, 255, 0)')

      sweepCtx.clearRect(0, 0, sweepCanvas.width, sweepCanvas.height)
      sweepCtx.fillStyle = gradient
      sweepCtx.fillRect(0, 0, sweepCanvas.width, sweepCanvas.height)
      sweepCtx.globalCompositeOperation = 'destination-in'
      sweepCtx.drawImage(maskCanvas, shiftX, shiftY)
      sweepCtx.globalCompositeOperation = 'source-over'

      ctx.drawImage(sweepCanvas, 0, 0)
    }
  }
}

function loop(now: number): void {
  if (disposed) return
  step(now)
  rafId = requestAnimationFrame(loop)
}

function onPointerMove(event: PointerEvent): void {
  if (!rootEl) return
  const rect = rootEl.getBoundingClientRect()
  pointer.x = event.clientX - rect.left
  pointer.y = event.clientY - rect.top
  pointer.active = true
}

function onPointerLeave(): void {
  pointer.active = false
}

onMounted(() => {
  rootEl = rootElRef.value
  canvasEl = canvasElRef.value
  if (!rootEl || !canvasEl) return
  ctx = canvasEl.getContext('2d')
  if (!ctx) return

  resolveColors()
  layout()

  if (reduced) {
    lastTime = performance.now()
    step(lastTime)
    return
  }

  observer = new ResizeObserver(() => {
    window.clearTimeout(resizeTimer)
    resizeTimer = window.setTimeout(layout, 160)
  })
  observer.observe(rootEl)

  window.addEventListener('pointermove', onPointerMove, { passive: true })
  window.addEventListener('pointerleave', onPointerLeave)
  rafId = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(rafId)
  window.clearTimeout(resizeTimer)
  observer?.disconnect()
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerleave', onPointerLeave)
})
</script>

<template>
  <div
    ref="rootElRef"
    class="pixel-wordmark"
    aria-hidden="true"
  >
    <canvas ref="canvasElRef"></canvas>
  </div>
</template>

<style scoped>
.pixel-wordmark {
  position: relative;
  overflow: hidden;
  pointer-events: none;
  color: var(--foreground);
}

.pixel-wordmark canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
