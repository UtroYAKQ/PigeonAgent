<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConsolePage from '@/components/console/ConsolePage.vue'
import ConsoleRail from '@/components/console/ConsoleRail.vue'
import ConsoleShell from '@/components/console/ConsoleShell.vue'
import { ADMIN_GROUP_ORDER, ADMIN_SECTIONS } from '@/components/admin/sections'
import type { ConsoleNavItem } from '@/components/console/types'

const route = useRoute()
const router = useRouter()
const shellRef = ref<InstanceType<typeof ConsoleShell> | null>(null)

const railItems = computed<ConsoleNavItem[]>(() =>
  ADMIN_SECTIONS.map(section => ({
    key: section.key,
    label: section.label,
    group: section.group,
    icon: section.icon,
  })),
)

const routeSection = computed(() => {
  const raw = route.params.section
  return Array.isArray(raw) ? raw[0] : raw
})

const activeSection = computed(
  () => ADMIN_SECTIONS.find(section => section.key === routeSection.value) ?? ADMIN_SECTIONS[0]!,
)

// 「平台配置」整组都是单列表单，窄栏更好读；运营组是表格页，用默认宽度。
// 从 sections.ts 的分组推导，新增配置项不会再漏改这里。
const CONFIG_SECTION_KEYS = new Set(
  ADMIN_SECTIONS.filter(section => section.group === '平台配置').map(section => section.key),
)
const pageWidth = computed<'default' | 'narrow'>(() =>
  CONFIG_SECTION_KEYS.has(activeSection.value.key) ? 'narrow' : 'default',
)

function openSection(key: string): void {
  if (key === activeSection.value.key) return
  void router.push({ name: 'admin', params: { section: key } })
}

function backToWorkspace(): void {
  void router.push('/chat')
}
</script>

<template>
  <ConsoleShell
    ref="shellRef"
    section="管理后台"
    :page="activeSection.title"
    :commands="railItems"
    @back="backToWorkspace"
    @command="openSection"
  >
    <template #rail="{ mobile, close }">
      <ConsoleRail
        :mobile="mobile"
        area="admin"
        title="管理后台"
        :groups="ADMIN_GROUP_ORDER"
        :items="railItems"
        :active="activeSection.key"
        @select="openSection"
        @back="() => { close(); backToWorkspace() }"
        @close="close"
      />
    </template>

    <ConsolePage
      :title="activeSection.title"
      :description="activeSection.description"
      :width="pageWidth"
    >
      <component
        :is="activeSection.panel"
        v-bind="activeSection.panelProps"
        @scroll-top="shellRef?.scrollToTop()"
      />
    </ConsolePage>
  </ConsoleShell>
</template>
