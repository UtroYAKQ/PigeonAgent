import type {
  ChatSession,
  SessionCreatePayload,
  SessionGroup,
  SessionList,
  SessionStatus,
  SessionUpdatePayload,
} from '@/types/api'
import { http } from '@/lib/http'

export const sessionsApi = {
  async list(params: {
    limit: number
    offset?: number
    status?: SessionStatus
    q?: string
  }): Promise<SessionList> {
    const { data } = await http.get<SessionList>('/sessions', { params })
    return data
  },

  async get(id: string): Promise<ChatSession> {
    const { data } = await http.get<ChatSession>(`/sessions/${id}`)
    return data
  },

  async create(payload: SessionCreatePayload): Promise<ChatSession> {
    const { data } = await http.post<ChatSession>('/sessions', payload)
    return data
  },

  async update(id: string, payload: SessionUpdatePayload): Promise<ChatSession> {
    const { data } = await http.patch<ChatSession>(`/sessions/${id}`, payload)
    return data
  },

  async remove(id: string): Promise<void> {
    await http.delete(`/sessions/${id}`)
  },

  async markRead(id: string): Promise<ChatSession> {
    const { data } = await http.post<ChatSession>(`/sessions/${id}/read`)
    return data
  },

  async switchLeaf(id: string, leafRunId: string | null): Promise<ChatSession> {
    const { data } = await http.post<ChatSession>(`/sessions/${id}/leaf`, { leaf_run_id: leafRunId })
    return data
  },
}

export const groupsApi = {
  async list(): Promise<SessionGroup[]> {
    const { data } = await http.get<{ items: SessionGroup[] }>('/groups')
    return data.items
  },

  async create(name: string): Promise<SessionGroup> {
    const { data } = await http.post<SessionGroup>('/groups', { name })
    return data
  },

  async rename(id: number, name: string): Promise<SessionGroup> {
    const { data } = await http.patch<SessionGroup>(`/groups/${id}`, { name })
    return data
  },

  async remove(id: number): Promise<void> {
    await http.delete(`/groups/${id}`)
  },
}
