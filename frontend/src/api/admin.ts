import type {
  AdminChatLogList,
  AdminCreditLogList,
  AdminOperationLogList,
  AdminSession,
  AdminSessionList,
  AdminStats,
  AdminUser,
  AdminUserList,
  AdminUserUpdatePayload,
  SessionRunList,
  SessionStatus,
} from '@/types/api'
import { API_BASE_URL, http } from '@/lib/http'

export const adminApi = {
  async stats(): Promise<AdminStats> {
    const { data } = await http.get<AdminStats>('/admin/stats')
    return data
  },

  async users(
    params: { q?: string; limit?: number; offset?: number } = {},
  ): Promise<AdminUserList> {
    const { data } = await http.get<AdminUserList>('/admin/users', { params })
    return data
  },

  async updateUser(id: string, payload: AdminUserUpdatePayload): Promise<AdminUser> {
    const { data } = await http.patch<AdminUser>(`/admin/users/${id}`, payload)
    return data
  },

  async resetUserPassword(id: string, newPassword: string): Promise<void> {
    await http.post(`/admin/users/${id}/password`, { new_password: newPassword })
  },

  async adjustCredits(id: string, delta: number, note?: string): Promise<AdminUser> {
    const { data } = await http.post<AdminUser>(`/admin/users/${id}/credits`, { delta, note })
    return data
  },

  async creditLogs(
    params: { user_id?: string; reason?: string; limit?: number; offset?: number } = {},
  ): Promise<AdminCreditLogList> {
    const { data } = await http.get<AdminCreditLogList>('/admin/credits/logs', { params })
    return data
  },

  async chatLogs(
    params: {
      user_id?: string
      session_id?: string
      status?: string
      limit?: number
      offset?: number
    } = {},
  ): Promise<AdminChatLogList> {
    const { data } = await http.get<AdminChatLogList>('/admin/chat-logs', { params })
    return data
  },

  async sessions(
    params: {
      q?: string
      status?: SessionStatus
      limit?: number
      offset?: number
    } = {},
  ): Promise<AdminSessionList> {
    const { data } = await http.get<AdminSessionList>('/admin/sessions', { params })
    return data
  },

  async session(id: string): Promise<AdminSession> {
    const { data } = await http.get<AdminSession>(`/admin/sessions/${id}`)
    return data
  },

  async sessionRuns(
    id: string,
    params: { before_run_id?: string; limit?: number } = {},
  ): Promise<SessionRunList> {
    const { data } = await http.get<SessionRunList>(`/admin/sessions/${id}/runs`, { params })
    return data
  },

  sessionEventsUrl(id: string, runId: string, after = 0): string {
    return `${API_BASE_URL}/admin/sessions/${id}/runs/${runId}/events?after=${after}`
  },

  async updateSession(id: string, status: SessionStatus): Promise<AdminSession> {
    const { data } = await http.patch<AdminSession>(`/admin/sessions/${id}`, { status })
    return data
  },

  async logs(
    params: {
      action?: string
      q?: string
      method?: string
      status?: number
      kind?: 'request' | 'admin'
      limit?: number
      offset?: number
    } = {},
  ): Promise<AdminOperationLogList> {
    const { data } = await http.get<AdminOperationLogList>('/admin/logs', { params })
    return data
  },
}
