import type { RegisterResult, TokenPair, User, UserPreferences } from '@/types/api'
import { http } from '@/lib/http'

export const authApi = {
  async login(email: string, password: string): Promise<TokenPair> {
    const { data } = await http.post<TokenPair>('/auth/login', { email, password })
    return data
  },

  async register(email: string, password: string, displayName?: string): Promise<RegisterResult> {
    const { data } = await http.post<RegisterResult>('/auth/register', {
      email,
      password,
      display_name: displayName?.trim() || undefined,
    })
    return data
  },

  async verify(email: string, code: string): Promise<TokenPair> {
    const { data } = await http.post<TokenPair>('/auth/verify', { email, code })
    return data
  },

  async resend(email: string): Promise<void> {
    await http.post('/auth/resend', { email })
  },

  async me(): Promise<User> {
    const { data } = await http.get<User>('/auth/me')
    return data
  },

  async updateProfile(patch: {
    display_name?: string | null
    avatar_file_id?: string | null
  }): Promise<User> {
    const { data } = await http.patch<User>('/auth/me', patch)
    return data
  },

  async updatePreferences(patch: Partial<UserPreferences>): Promise<User> {
    const { data } = await http.patch<User>('/auth/me/preferences', patch)
    return data
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<TokenPair> {
    const { data } = await http.post<TokenPair>('/auth/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    return data
  },

  /** 登出所有设备：服务端作废已签发的 access/refresh，这台也一样掉线。 */
  async signOutEverywhere(): Promise<void> {
    await http.post('/auth/logout-all')
  },
}
