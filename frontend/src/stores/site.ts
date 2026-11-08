import { ref } from 'vue'
import { defineStore } from 'pinia'

import { configsApi } from '@/api/configs'

const DEFAULT_NAME = 'PigeonAgent'

export const useSiteStore = defineStore('site', () => {
  const name = ref(DEFAULT_NAME)
  const description = ref('')
  const logoUrl = ref<string | null>(null)
  const loaded = ref(false)

  async function load(): Promise<void> {
    try {
      const data = await configsApi.public()
      name.value = data.site_name.trim() || DEFAULT_NAME
      description.value = data.site_description.trim()
      logoUrl.value = data.site_logo_url
      loaded.value = true
    } catch {
      // 公开配置失败不阻塞应用，保留内置品牌默认值
    }
  }

  return { name, description, logoUrl, loaded, load }
})
