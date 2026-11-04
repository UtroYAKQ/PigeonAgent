import { computed, ref, watch, type Ref } from 'vue'
import { useLocalStorage, usePreferredDark } from '@vueuse/core'
import { defineStore } from 'pinia'
import { toast } from 'vue-sonner'

import { errorMessage } from '@/lib/http'
import { DEFAULT_USER_PREFERENCES } from '@/lib/preferences'
import { useAuthStore } from '@/stores/auth'
import type { StoredUserPreferences, UserPreferences } from '@/types/api'

export type ThemePreference = UserPreferences['theme']
export type SendShortcut = UserPreferences['send_shortcut']

export const useUiStore = defineStore('ui', () => {
  const auth = useAuthStore()
  const preferredDark = usePreferredDark()
  // 所有 UI 偏好都在本地留一份：首屏和退出登录后直接沿用，避免主题、快捷键等先闪回默认值
  const theme = useLocalStorage<ThemePreference>('pigeon.theme', DEFAULT_USER_PREFERENCES.theme)
  const sendShortcut = useLocalStorage<SendShortcut>(
    'pigeon.send-shortcut',
    DEFAULT_USER_PREFERENCES.send_shortcut,
  )
  const autoExpandThinking = useLocalStorage(
    'pigeon.auto-expand-thinking',
    DEFAULT_USER_PREFERENCES.auto_expand_thinking,
  )
  const autoExpandToolDetails = useLocalStorage(
    'pigeon.auto-expand-tool-details',
    DEFAULT_USER_PREFERENCES.auto_expand_tool_details,
  )
  const wrapCode = useLocalStorage('pigeon.wrap-code', DEFAULT_USER_PREFERENCES.wrap_code)
  const sidebarCollapsed = useLocalStorage('pigeon.sidebar-collapsed', false)
  const mobileSidebarOpen = ref(false)
  const sessionSearchOpen = ref(false)

  const isDark = computed(() => (theme.value === 'dark' ? true : theme.value === 'light' ? false : preferredDark.value))

  watch(
    isDark,
    (dark) => {
      document.documentElement.classList.toggle('dark', dark)
      document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#212121' : '#ffffff')
    },
    { immediate: true },
  )

  /** 账号只覆盖它显式存过的键；没表过态的项沿用本地缓存，免得服务端默认值冒充用户选择。 */
  function applyPreferences(stored?: StoredUserPreferences | null): void {
    if (!stored) return
    if (stored.theme != null) theme.value = stored.theme
    if (stored.send_shortcut != null) sendShortcut.value = stored.send_shortcut
    if (stored.auto_expand_thinking != null) autoExpandThinking.value = stored.auto_expand_thinking
    if (stored.auto_expand_tool_details != null) {
      autoExpandToolDetails.value = stored.auto_expand_tool_details
    }
    if (stored.wrap_code != null) wrapCode.value = stored.wrap_code
  }

  watch(
    () => auth.user?.id,
    () => {
      // 退出/游客状态直接保留本地缓存，避免主题在退出瞬间闪回默认值。
      if (!auth.user) return
      applyPreferences(auth.user.preferences)
    },
    { immediate: true },
  )

  function persist(patch: Partial<UserPreferences>): void {
    if (!auth.user) return
    void auth.updatePreferences(patch).catch((error: unknown) => {
      toast.error('偏好保存失败', { description: errorMessage(error) })
    })
  }

  /** 五个偏好 setter 同形：先写本地缓存，再把这一项送服务端。加新偏好只要多一行。 */
  function bindPreference<K extends keyof UserPreferences>(
    key: K,
    target: Ref<UserPreferences[K]>,
  ): (next: UserPreferences[K]) => void {
    return next => {
      target.value = next
      persist({ [key]: next } as Partial<UserPreferences>)
    }
  }

  const setTheme = bindPreference('theme', theme)
  const setSendShortcut = bindPreference('send_shortcut', sendShortcut)
  const setAutoExpandThinking = bindPreference('auto_expand_thinking', autoExpandThinking)
  const setAutoExpandToolDetails = bindPreference('auto_expand_tool_details', autoExpandToolDetails)
  const setWrapCode = bindPreference('wrap_code', wrapCode)

  function cycleTheme(): void {
    setTheme(theme.value === 'light' ? 'dark' : theme.value === 'dark' ? 'system' : 'light')
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function collapseSidebar(): void {
    sidebarCollapsed.value = true
  }

  function openMobileSidebar(): void {
    mobileSidebarOpen.value = true
  }

  function closeMobileSidebar(): void {
    mobileSidebarOpen.value = false
  }

  function toggleSessionSearch(): void {
    sessionSearchOpen.value = !sessionSearchOpen.value
  }

  function closeSessionSearch(): void {
    sessionSearchOpen.value = false
  }

  return {
    theme,
    isDark,
    sendShortcut,
    sidebarCollapsed,
    autoExpandThinking,
    autoExpandToolDetails,
    wrapCode,
    mobileSidebarOpen,
    sessionSearchOpen,
    setTheme,
    setSendShortcut,
    setAutoExpandThinking,
    setAutoExpandToolDetails,
    setWrapCode,
    cycleTheme,
    toggleSidebar,
    collapseSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    toggleSessionSearch,
    closeSessionSearch,
  }
})
