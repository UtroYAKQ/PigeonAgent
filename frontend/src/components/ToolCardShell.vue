<script setup lang="ts">
import { ChevronDown } from "lucide-vue-next";

/**
 * 消息流里工具卡的外壳：图标片 + 行首标签 + 摘要 + 展开区。
 * 定制卡只负责塞图标和正文，行结构不再各写一份。
 */
defineProps<{
  tone: string;
  expanded: boolean;
  label: string;
  labelClass?: string;
  summary?: string;
  summaryClass?: string;
  summaryMono?: boolean;
  summaryTitle?: string;
}>();

const emit = defineEmits<{ (event: "toggle"): void }>();
</script>

<template>
  <div class="rounded-surface border border-hair bg-surface">
    <button
      type="button"
      class="flex w-full items-center gap-2 px-3 py-2 text-left text-ui text-muted"
      :aria-expanded="expanded"
      @click="emit('toggle')"
    >
      <span :class="['grid size-5 shrink-0 place-items-center rounded-md', tone]">
        <slot name="icon" />
      </span>
      <span :class="['shrink-0 whitespace-nowrap', labelClass]">{{ label }}</span>
      <span
        v-if="summary"
        :class="[
          'min-w-0 truncate text-meta',
          summaryMono ? 'font-mono' : '',
          summaryClass ?? 'text-ink',
        ]"
        :title="summaryTitle"
        >{{ summary }}</span
      >
      <div class="ml-auto flex shrink-0 items-center gap-2">
        <slot name="trailing" />
        <ChevronDown
          :size="14"
          :class="['shrink-0 text-faint transition-transform', expanded ? 'rotate-180' : '']"
        />
      </div>
    </button>

    <div v-if="expanded" class="border-t border-hair px-3 py-2.5">
      <slot />
    </div>
  </div>
</template>
