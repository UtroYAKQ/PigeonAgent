import type { Capabilities } from '@/types/api'
import { http } from '@/lib/http'

export const capabilitiesApi = {
  async get(): Promise<Capabilities> {
    const { data } = await http.get<Capabilities>('/capabilities')
    return data
  },
}
