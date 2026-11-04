import type {
  LlmModel,
  LlmModelCreatePayload,
  LlmModelList,
  LlmModelUpdatePayload,
} from '@/types/api'
import { http } from '@/lib/http'

export const modelsApi = {
  async list(): Promise<LlmModelList> {
    const { data } = await http.get<LlmModelList>('/models', { params: { limit: 200 } })
    return data
  },

  async create(payload: LlmModelCreatePayload): Promise<LlmModel> {
    const { data } = await http.post<LlmModel>('/models', payload)
    return data
  },

  async update(id: number, payload: LlmModelUpdatePayload): Promise<LlmModel> {
    const { data } = await http.patch<LlmModel>(`/models/${id}`, payload)
    return data
  },

  async remove(id: number): Promise<void> {
    await http.delete(`/models/${id}`)
  },
}
