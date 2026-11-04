import type { UsageOverview } from '@/types/api'
import { http } from '@/lib/http'

export const usageApi = {
  async overview(): Promise<UsageOverview> {
    const { data } = await http.get<UsageOverview>('/usage/me')
    return data
  },
}
