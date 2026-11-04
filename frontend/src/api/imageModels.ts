import type {
  ImageModel,
  ImageModelCreatePayload,
  ImageModelList,
  ImageModelUpdatePayload,
  ImageProviderPreset,
} from '@/types/api'
import { http } from '@/lib/http'

export const imageModelsApi = {
  async list(): Promise<ImageModelList> {
    const { data } = await http.get<ImageModelList>('/image-models', { params: { limit: 200 } })
    return data
  },

  async listProviders(): Promise<ImageProviderPreset[]> {
    const { data } = await http.get<ImageProviderPreset[]>('/image-models/providers')
    return data
  },

  async create(payload: ImageModelCreatePayload): Promise<ImageModel> {
    const { data } = await http.post<ImageModel>('/image-models', payload)
    return data
  },

  async update(id: number, payload: ImageModelUpdatePayload): Promise<ImageModel> {
    const { data } = await http.patch<ImageModel>(`/image-models/${id}`, payload)
    return data
  },

  async remove(id: number): Promise<void> {
    await http.delete(`/image-models/${id}`)
  },
}
