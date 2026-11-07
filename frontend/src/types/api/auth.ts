/* auth 领域类型。 */

import type { UUID } from './common'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type ThemePreference = 'light' | 'dark' | 'system'
export type SendShortcut = 'enter' | 'ctrl-enter'

export interface UserPreferences {
  theme: ThemePreference
  send_shortcut: SendShortcut
  auto_expand_thinking: boolean
  auto_expand_tool_details: boolean
  wrap_code: boolean
}

/** 账号显式存过的偏好；缺键表示这个账号在该项上没表过态，本地缓存继续生效。 */
export type StoredUserPreferences = Partial<UserPreferences>

export interface User {
  id: UUID
  email: string
  display_name: string | null
  avatar_file_id: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string
  credits_balance: number
  preferences: StoredUserPreferences
}

export interface RegisterResult {
  verification_required: boolean
  user?: User | null
  tokens?: TokenPair | null
}
