import type { UserPreferences } from '@/types/api'

export const DEFAULT_USER_PREFERENCES: UserPreferences = {
  theme: 'dark',
  send_shortcut: 'enter',
  auto_expand_thinking: false,
  auto_expand_tool_details: false,
  wrap_code: false,
}
