import type { SiteLogoRead } from '@/types/api'
import { http } from '@/lib/http'

export const siteApi = {
  async uploadLogo(file: File): Promise<SiteLogoRead> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post<SiteLogoRead>('/site/logo', form)
    return data
  },

  async removeLogo(): Promise<void> {
    await http.delete('/site/logo')
  },
}
