import type { SessionShare, SharedConversation, UUID } from '@/types/api'
import { http } from '@/lib/http'

export const sharesApi = {
  async create(sessionId: UUID, expiresInDays: number): Promise<SessionShare> {
    const { data } = await http.post<SessionShare>('/shares', {
      session_id: sessionId,
      expires_in_days: expiresInDays,
    })
    return data
  },

  async list(): Promise<SessionShare[]> {
    const { data } = await http.get<SessionShare[]>('/shares')
    return data
  },

  async revoke(shareId: UUID): Promise<void> {
    await http.delete(`/shares/${shareId}`)
  },

  /** 公开读取：访客不需要登录态，链接口令就在路径里。 */
  async read(token: string, beforeRunId?: UUID): Promise<SharedConversation> {
    const { data } = await http.get<SharedConversation>(
      `/public/shares/${encodeURIComponent(token)}`,
      { params: beforeRunId ? { before_run_id: beforeRunId } : undefined },
    )
    return data
  },
}
