import type { AppConfigItem, AppConfigList, PublicConfig } from '@/types/api'
import { http } from '@/lib/http'

export const configsApi = {
  async public(): Promise<PublicConfig> {
    const { data } = await http.get<PublicConfig>('/configs/public')
    return data
  },

  async list(): Promise<AppConfigList> {
    const { data } = await http.get<AppConfigList>('/configs')
    return data
  },

  async update(key: string, value: string | number | null): Promise<AppConfigItem> {
    const { data } = await http.patch<AppConfigItem>(`/configs/${key}`, { value })
    return data
  },
}
