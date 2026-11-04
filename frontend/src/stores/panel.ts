/** 右侧面板的标签页状态：按会话分组，与对话流本身无关。 */

import { ref } from 'vue'
import { defineStore } from 'pinia'

import { randomUuid } from '@/lib/ids'
import type { PanelTab, PanelTabInput } from '@/types/panel'
import type { UUID } from '@/types/api'

export interface PreviewInput {
  sessionId: UUID
  toolCallId: string
  title: string
  html: string
}

export const usePanelStore = defineStore('panel', () => {
  const tabs = ref<PanelTab[]>([])
  const activeTabId = ref<string | null>(null)

  function tabsOf(sessionId: UUID | null): PanelTab[] {
    return sessionId ? tabs.value.filter(item => item.sessionId === sessionId) : []
  }

  /** 当前会话该展示哪个标签；没有显式选中的就落到最后一个。 */
  function activeTab(sessionId: UUID | null): PanelTab | null {
    const list = tabsOf(sessionId)
    if (!list.length) return null
    return list.find(item => item.id === activeTabId.value) ?? list[list.length - 1] ?? null
  }

  function openTab(next: PanelTabInput): string {
    const tab: PanelTab = { ...next, id: randomUuid() }
    tabs.value = [...tabs.value, tab]
    activeTabId.value = tab.id
    return tab.id
  }

  /** 预览面板：HTML 直接进 iframe，源码另开一个 code 标签。 */
  function openPreview(next: PreviewInput): void {
    openTab({
      sessionId: next.sessionId,
      type: 'html',
      title: next.title,
      content: next.html,
      sourceId: next.toolCallId,
    })
  }

  function selectTab(id: string): void {
    activeTabId.value = id
  }

  function closeTab(sessionId: UUID | null, id: string): void {
    const list = tabsOf(sessionId)
    const index = list.findIndex(item => item.id === id)
    if (index < 0) return
    tabs.value = tabs.value.filter(item => item.id !== id)
    if (activeTabId.value === id) {
      // 关掉当前标签后选相邻的那个：优先右边，没有才往左
      const next = list[index + 1] ?? list[index - 1] ?? null
      activeTabId.value = next?.id ?? null
    }
  }

  /** 会话被删除或切走时回收它的标签；活动标签没了就一起清掉。 */
  function closeTabs(sessionId: UUID | null): void {
    if (!sessionId) {
      activeTabId.value = null
      return
    }
    tabs.value = tabs.value.filter(item => item.sessionId !== sessionId)
    if (!tabs.value.some(item => item.id === activeTabId.value)) {
      activeTabId.value = null
    }
  }

  return {
    tabs,
    activeTabId,
    tabsOf,
    activeTab,
    openTab,
    openPreview,
    selectTab,
    closeTab,
    closeTabs,
  }
})
