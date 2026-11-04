<script setup lang="ts">
import { computed, reactive } from 'vue'
import { Globe2 } from '@lucide/vue'

import { TooltipHint } from '@/components/ui/tooltip'
import { hostOf } from '@/lib/format'
import type { SourceRef } from '@/lib/turnModel'

const props = defineProps<{ sources: SourceRef[] }>()

const brokenIcons = reactive(new Set<string>())

const items = computed(() =>
  props.sources.slice(0, 4).map((source) => {
    try {
      const parsed = new URL(source.url)
      const path = parsed.pathname === '/' ? '' : parsed.pathname
      return {
        ...source,
        host: hostOf(source.url),
        path: path.length > 24 ? `${path.slice(0, 23)}…` : path,
      }
    } catch {
      return { ...source, host: source.url, path: '' }
    }
  }),
)

function iconBroken(icon: string | null): boolean {
  return Boolean(icon && brokenIcons.has(icon))
}

function onIconError(icon: string | null): void {
  if (icon) brokenIcons.add(icon)
}
</script>

<template>
  <div v-if="items.length" class="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
    <span class="text-[11.5px] text-muted-foreground">{{ sources.length }} 个引用来源</span>
    <span class="h-3 w-px bg-border" />
    <TooltipHint
      v-for="source in items"
      :key="source.url"
      :text="source.url"
    >
      <a
        :href="source.url"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground transition-colors hover:border-foreground/20 hover:text-foreground"
      >
        <img
          v-if="source.icon && !iconBroken(source.icon)"
          :src="source.icon"
          alt=""
          class="size-3.5 shrink-0 rounded-[3px] object-contain"
          loading="lazy"
          referrerpolicy="no-referrer"
          @error="onIconError(source.icon)"
        >
        <Globe2 v-else class="size-3 shrink-0" />
        <span class="truncate">{{ source.host }}</span>
      </a>
    </TooltipHint>
  </div>
</template>
