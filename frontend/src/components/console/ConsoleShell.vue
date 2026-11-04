<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useEventListener, useLocalStorage, useMediaQuery } from '@vueuse/core'
import {
  Home,
  PanelLeft,
  Search,
} from '@lucide/vue'

import ConsoleCommandMenu from '@/components/console/ConsoleCommandMenu.vue'
import type { ConsoleCommandItem } from '@/components/console/types'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import { TooltipHint } from '@/components/ui/tooltip'

const props = defineProps<{
  section: string
  page: string
  commands: ConsoleCommandItem[]
}>()

const emit = defineEmits<{
  back: []
  command: [key: string]
}>()

const route = useRoute()
const isDesktop = useMediaQuery('(min-width: 1024px)')
const railCollapsed = useLocalStorage('pigeon.console-rail-collapsed', false)
const mobileNavOpen = ref(false)
const commandOpen = ref(false)
const scroller = ref<HTMLElement | null>(null)

const shortcutKey = computed(() =>
  typeof navigator !== 'undefined' && navigator.userAgent.includes('Mac') ? '⌘' : 'Ctrl',
)

const commandItems = computed<ConsoleCommandItem[]>(() => [
  { key: '__workspace', label: '返回工作区', group: '导航', icon: Home },
  ...props.commands,
])

watch(
  () => route.fullPath,
  () => {
    if (scroller.value) scroller.value.scrollTop = 0
  },
)

function scrollToTop(): void {
  scroller.value?.scrollTo({ top: 0, behavior: 'smooth' })
}

function openNav(): void {
  if (isDesktop.value) {
    railCollapsed.value = !railCollapsed.value
    return
  }
  mobileNavOpen.value = true
}

function closeMobileNav(): void {
  mobileNavOpen.value = false
}

function onWindowKeydown(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    commandOpen.value = !commandOpen.value
  }
}

function selectCommand(key: string): void {
  if (key === '__workspace') {
    emit('back')
    return
  }
  emit('command', key)
}

defineSlots<{
  rail(props: { mobile: boolean; close: () => void }): unknown
  default(): unknown
}>()

defineExpose({ scrollToTop })

useEventListener(window, 'keydown', onWindowKeydown)
</script>

<template>
  <div class="console-surface flex h-dvh w-full overflow-hidden bg-background text-foreground">
    <aside
      class="hidden h-full shrink-0 overflow-hidden transition-[width] duration-200 ease-linear lg:block"
      :class="railCollapsed ? 'w-0 border-r-0' : 'w-64 border-r border-sidebar-border'"
    >
      <slot name="rail" :mobile="false" :close="closeMobileNav" />
    </aside>

    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center gap-2 border-b border-border/70 px-3 sm:px-4">
        <TooltipHint :text="isDesktop ? (railCollapsed ? '展开侧栏' : '收起侧栏') : '打开导航'">
          <button
            type="button"
            class="grid size-9 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            :aria-label="isDesktop ? (railCollapsed ? '展开侧栏' : '收起侧栏') : '打开导航'"
            @click="openNav"
          >
            <PanelLeft class="size-[18px]" :stroke-width="1.8" />
          </button>
        </TooltipHint>

        <button
          type="button"
          class="hidden h-8 w-[224px] items-center gap-2 rounded-md border border-border bg-background px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-muted/50 sm:flex"
          @click="commandOpen = true"
        >
          <Search class="size-3.5 shrink-0" />
          <span class="flex-1 text-left">搜索菜单</span>
          <span class="flex items-center gap-1">
            <span class="rounded border border-border bg-muted px-1 py-0.5 text-[9px] leading-none">{{ shortcutKey }}</span>
            <span class="rounded border border-border bg-muted px-1 py-0.5 text-[9px] leading-none">K</span>
          </span>
        </button>

        <button
          type="button"
          class="grid size-8 place-items-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:hidden"
          aria-label="搜索菜单"
          @click="commandOpen = true"
        >
          <Search class="size-3.5" />
        </button>
      </header>

      <main ref="scroller" class="min-h-0 flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>

    <Sheet v-model:open="mobileNavOpen">
      <SheetContent
        side="left"
        :show-close-button="false"
        class="console-surface w-[284px] max-w-[86vw] border-r border-sidebar-border bg-sidebar p-0"
      >
        <SheetTitle class="sr-only">导航</SheetTitle>
        <SheetDescription class="sr-only">设置与管理后台导航</SheetDescription>
        <slot name="rail" :mobile="true" :close="closeMobileNav" />
      </SheetContent>
    </Sheet>

    <ConsoleCommandMenu v-model:open="commandOpen" :items="commandItems" @select="selectCommand" />
  </div>
</template>
