import type { ResumeRunPayload, RunCreatePayload, SessionRunList } from '@/types/api'
import { API_BASE_URL, http } from '@/lib/http'

export const runsApi = {
  async list(
    sessionId: string,
    params: { before_run_id?: string; limit?: number } = {},
  ): Promise<SessionRunList> {
    const { data } = await http.get<SessionRunList>(`/sessions/${sessionId}/runs`, { params })
    return data
  },

  async create(sessionId: string, payload: RunCreatePayload): Promise<string> {
    const { data } = await http.post<{ run_id: string }>(`/sessions/${sessionId}/runs`, payload)
    return data.run_id
  },

  async resume(sessionId: string, payload: ResumeRunPayload): Promise<string> {
    const { data } = await http.post<{ run_id: string }>(
      `/sessions/${sessionId}/runs/resume`,
      payload,
    )
    return data.run_id
  },

  async cancel(sessionId: string, runId: string): Promise<void> {
    await http.post(`/sessions/${sessionId}/runs/${runId}/cancel`)
  },

  eventsUrl(sessionId: string, runId: string, after = 0): string {
    return `${API_BASE_URL}/sessions/${sessionId}/runs/${runId}/events?after=${after}`
  },
}
