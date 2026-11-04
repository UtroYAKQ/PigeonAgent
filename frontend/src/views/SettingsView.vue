<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  Archive,
  Keyboard,
  Palette,
  Share2,
  SlidersHorizontal,
  UserRound,
} from '@lucide/vue'

import ConsolePage from '@/components/console/ConsolePage.vue'
import ConsoleRail from '@/components/console/ConsoleRail.vue'
import ConsoleShell from '@/components/console/ConsoleShell.vue'
import type { ConsoleNavItem } from '@/components/console/types'
import AccountSettingsPanel from '@/components/settings/AccountSettingsPanel.vue'
import AppearanceSettingsPanel from '@/components/settings/AppearanceSettingsPanel.vue'
import ArchivedSessionsPanel from '@/components/settings/ArchivedSessionsPanel.vue'
import ConversationPreferencesPanel from '@/components/settings/ConversationPreferencesPanel.vue'
import SharesSettingsPanel from '@/components/settings/SharesSettingsPanel.vue'
import ShortcutsSettingsPanel from '@/components/settings/ShortcutsSettingsPanel.vue'
import UsageSettingsPanel from '@/components/settings/UsageSettingsPanel.vue'

type SectionKey =
  | 'appearance'
  | 'archive'
  | 'usage'
  | 'shortcuts'
  | 'preferences'
  | 'shares'
  | 'account'

interface SectionDef {
  key: SectionKey
  label: string
  group: string
  title: string
  description: string
  icon: Component
}

const SECTIONS: SectionDef[] = [
  {
    key: 'appearance',
    label: '外观',
    group: '基础设置',
    title: '外观',
    description: '选择界面主题。偏好保存在你的账号中，登录其他设备也会同步。',
    icon: Palette,
  },
  {
    key: 'archive',
    label: '归档',
    group: '工作区',
    title: '归档',
    description: '已归档的对话会保留在这里，恢复后回到侧栏列表。',
    icon: Archive,
  },
  {
    key: 'usage',
    label: '用量',
    group: '工作区',
    title: '我的用量',
    description: '积分余额、每日 token 消耗热力图、模型分布与最近对话。',
    icon: Activity,
  },
  {
    key: 'shortcuts',
    label: '快捷键',
    group: '个人',
    title: '快捷键',
    description: '设置当前账号的发送快捷键。',
    icon: Keyboard,
  },
  {
    key: 'preferences',
    label: '对话偏好',
    group: '个人',
    title: '对话偏好',
    description: '当前账号的对话展示偏好，保存到账号并跨设备同步。',
    icon: SlidersHorizontal,
  },
  {
    key: 'shares',
    label: '分享链接',
    group: '个人',
    title: '分享链接',
    description: '这个账号发出的只读对话链接，可查看访问次数并随时撤销。',
    icon: Share2,
  },
  {
    key: 'account',
    label: '账号',
    group: '个人',
    title: '账号设置',
    description: '更新显示名称、修改密码和登录状态。',
    icon: UserRound,
  },
]

const GROUP_ORDER = ['基础设置', '工作区', '个人']

const route = useRoute()
const router = useRouter()

const railItems = computed<ConsoleNavItem[]>(() =>
  SECTIONS.map(section => ({
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

const activeSection = computed<SectionKey>(() => {
  const found = SECTIONS.find(section => section.key === routeSection.value)
  return found?.key ?? 'appearance'
})

const activeDef = computed<SectionDef>(
  () => SECTIONS.find(section => section.key === activeSection.value) ?? SECTIONS[0]!,
)

function openSection(key: string): void {
  if (key === activeSection.value) return
  void router.push({ name: 'settings', params: { section: key }, query: route.query })
}

function backToWorkspace(): void {
  const from = typeof route.query.from === 'string' ? route.query.from : ''
  if (from.startsWith('/') && !from.startsWith('//')) {
    void router.push(from)
    return
  }
  void router.push('/chat')
}
</script>

<template>
  <ConsoleShell
    section="设置"
    :page="activeDef.title"
    :commands="railItems"
    @back="backToWorkspace"
    @command="openSection"
  >
    <template #rail="{ mobile, close }">
      <ConsoleRail
        :mobile="mobile"
        area="settings"
        title="设置"
        :groups="GROUP_ORDER"
        :items="railItems"
        :active="activeSection"
        @select="openSection"
        @back="() => { close(); backToWorkspace() }"
        @close="close"
      />
    </template>

    <ConsolePage
      :title="activeDef.title"
      :description="activeDef.description"
      width="narrow"
    >
      <AppearanceSettingsPanel v-if="activeSection === 'appearance'" />

      <ArchivedSessionsPanel v-else-if="activeSection === 'archive'" />

      <UsageSettingsPanel v-else-if="activeSection === 'usage'" />

      <ShortcutsSettingsPanel v-else-if="activeSection === 'shortcuts'" />

      <ConversationPreferencesPanel v-else-if="activeSection === 'preferences'" />

      <SharesSettingsPanel v-else-if="activeSection === 'shares'" />

      <AccountSettingsPanel v-else-if="activeSection === 'account'" />
    </ConsolePage>
  </ConsoleShell>
</template>
