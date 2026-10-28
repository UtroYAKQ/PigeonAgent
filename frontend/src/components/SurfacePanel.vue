<script setup lang="ts">
import { ExternalLink, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { useSurfaces } from "../composables/useSurfaces";
import { codeHtml } from "../render/infer";

const MIN_PANEL = 320;
/** 侧栏 272 + 对话列可读下限 420；预览再宽就只能挤压对话了。 */
const MIN_REST = 700;
const STORAGE_KEY = "pigeon.surface.width";

const { stack, active, activate, close } = useSurfaces();

/** 代码页复用消息里那套高亮；认不出的语言就原样显示。 */
const sourceHtml = computed(() =>
  active.value?.kind === "code" ? codeHtml(active.value.body, active.value.lang ?? "") : "",
);

const viewport = ref(window.innerWidth);

const maxWidth = computed(() => Math.max(viewport.value - MIN_REST, MIN_PANEL));

function clamp(value: number): number {
  return Math.min(Math.max(Math.round(value), MIN_PANEL), maxWidth.value);
}

const width = ref(clamp(Number(localStorage.getItem(STORAGE_KEY)) || window.innerWidth * 0.46));

function remember(): void {
  localStorage.setItem(STORAGE_KEY, String(width.value));
}

/** 窗口变小后要重新收敛，否则预览会把对话列挤到可读下限以下。 */
function onResize(): void {
  viewport.value = window.innerWidth;
  const next = clamp(width.value);
  if (next !== width.value) {
    width.value = next;
    remember();
  }
}

onMounted(() => window.addEventListener("resize", onResize));
onBeforeUnmount(() => window.removeEventListener("resize", onResize));

function openInNewTab(): void {
  if (!active.value) return;
  const { kind, body } = active.value;
  const url = URL.createObjectURL(
    new Blob([body], { type: kind === "html" ? "text/html" : "text/plain;charset=utf-8" }),
  );
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

let dragging = false;

function startDrag(event: PointerEvent): void {
  dragging = true;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
}

function onDrag(event: PointerEvent): void {
  if (!dragging) return;
  width.value = clamp(window.innerWidth - event.clientX);
}

function endDrag(event: PointerEvent): void {
  if (!dragging) return;
  dragging = false;
  (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  remember();
}

function nudge(step: number): void {
  width.value = clamp(width.value + step);
  remember();
}

function reset(): void {
  width.value = clamp(Math.round(window.innerWidth * 0.46));
  remember();
}
</script>

<template>
  <template v-if="active">
    <div
      class="w-2 shrink-0 cursor-col-resize border-x border-hair bg-canvas transition-colors hover:bg-hover focus-visible:bg-hover focus-visible:outline-none max-md:hidden"
      role="separator"
      aria-orientation="vertical"
      aria-label="调整预览宽度"
      tabindex="0"
      :aria-valuenow="width"
      :aria-valuemin="MIN_PANEL"
      :aria-valuemax="maxWidth"
      @pointerdown="startDrag"
      @pointermove="onDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
      @keydown.left.prevent="nudge(-24)"
      @keydown.right.prevent="nudge(24)"
      @dblclick="reset"
    />
    <aside
      class="flex h-full w-[var(--surface-w)] min-w-[320px] flex-col bg-canvas max-md:fixed max-md:inset-0 max-md:z-40 max-md:w-full max-md:min-w-0"
      :style="{ '--surface-w': `${width}px` }"
    >
      <header class="flex h-11 shrink-0 items-center gap-1 border-b border-hair px-2">
        <div class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          <div
            v-for="surface in stack"
            :key="surface.id"
            :class="[
              'flex max-w-[200px] shrink-0 items-center rounded-control py-1 pl-2.5 pr-1 transition-colors',
              surface.id === active.id
                ? 'bg-hover text-ink'
                : 'text-faint hover:bg-hover hover:text-ink',
            ]"
          >
            <button
              class="min-w-0 truncate text-left text-meta"
              :class="surface.id === active.id ? 'font-medium' : ''"
              @click="activate(surface.id)"
            >
              {{ surface.title }}
            </button>
            <button
              class="ml-1 shrink-0 rounded-control p-0.5 opacity-60 transition-opacity hover:opacity-100"
              :aria-label="`关闭 ${surface.title}`"
              @click="close(surface.id)"
            >
              <X :size="12" :stroke-width="1.7" />
            </button>
          </div>
        </div>
        <button
          class="shrink-0 rounded-control p-1.5 text-faint transition-colors hover:bg-hover hover:text-ink"
          title="在新窗口打开"
          @click="openInNewTab"
        >
          <ExternalLink :size="15" :stroke-width="1.7" />
        </button>
      </header>
      <!-- 模型给的 HTML 一律当不可信输入：sandbox 不给 allow-same-origin，脚本碰不到本站的存储和身份 -->
      <iframe
        v-if="active.kind === 'html'"
        :srcdoc="active.body"
        :title="active.title"
        class="min-h-0 w-full flex-1 border-0 bg-white"
        sandbox="allow-scripts"
        referrerpolicy="no-referrer"
      />
      <pre
        v-else
        class="min-h-0 flex-1 overflow-auto px-4 py-3 font-mono text-meta leading-relaxed whitespace-pre-wrap break-words text-ink"
        ><code v-if="sourceHtml" v-html="sourceHtml" /><code v-else>{{ active.body }}</code></pre
      >
    </aside>
  </template>
</template>
