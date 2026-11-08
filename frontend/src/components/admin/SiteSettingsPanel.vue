<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { ImagePlus, Loader2, RefreshCw, Trash2 } from '@lucide/vue'

import BrandMark from '@/components/brand/BrandMark.vue'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { configsApi } from '@/api/configs'
import { siteApi } from '@/api/site'
import { errorMessage } from '@/lib/http'
import { useSiteStore } from '@/stores/site'

const site = useSiteStore()
const name = ref('')
const description = ref('')
const logoUrl = ref<string | null>(null)
const loading = ref(true)
const saving = ref(false)
const uploading = ref(false)
const removing = ref(false)
const confirmRemove = ref(false)
const loadError = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const previewSrc = computed(() => logoUrl.value)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const data = await configsApi.list()
    const byKey = new Map(data.items.map(item => [item.key, item]))
    name.value = byKey.get('site_name')?.value ?? ''
    description.value = byKey.get('site_description')?.value ?? ''
    logoUrl.value = byKey.get('site_logo_url')?.value ?? null
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  const nextName = name.value.trim()
  if (!nextName) {
    toast.error('站点名称不能为空')
    return
  }
  saving.value = true
  try {
    await configsApi.update('site_name', nextName)
    await configsApi.update('site_description', description.value.trim() || null)
    await site.load()
    toast.success('站点信息已保存')
  } catch (error) {
    toast.error('站点信息保存失败', { description: errorMessage(error) })
  } finally {
    saving.value = false
  }
}

function pickLogo(): void {
  fileInput.value?.click()
}

async function onLogoFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)) {
    toast.error('Logo 只支持 PNG、JPEG、WebP 或 GIF')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    toast.error('Logo 不能超过 2 MB')
    return
  }
  uploading.value = true
  try {
    const result = await siteApi.uploadLogo(file)
    logoUrl.value = result.site_logo_url
    await site.load()
    toast.success('站点 Logo 已更新')
  } catch (error) {
    toast.error('Logo 上传失败', { description: errorMessage(error) })
  } finally {
    uploading.value = false
  }
}

async function removeLogo(): Promise<void> {
  if (removing.value) return
  if (!confirmRemove.value) {
    confirmRemove.value = true
    return
  }
  removing.value = true
  try {
    await siteApi.removeLogo()
    logoUrl.value = null
    confirmRemove.value = false
    await site.load()
    toast.success('站点 Logo 已移除')
  } catch (error) {
    toast.error('移除 Logo 失败', { description: errorMessage(error) })
  } finally {
    removing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">站点名称和 Logo 会用于登录页、侧栏、分享页与浏览器标题。</p>
      <Button variant="outline" class="h-9" :disabled="loading" @click="load">
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <div v-if="loading" class="space-y-3">
      <div v-for="index in 3" :key="index" class="space-y-2">
        <div class="h-3 w-28 animate-pulse rounded-full bg-muted" />
        <div class="h-9 w-2/3 animate-pulse rounded-md bg-muted" />
      </div>
    </div>

    <div v-else-if="loadError" class="rounded-lg border border-border bg-card px-4 py-16 text-center">
      <p class="text-sm font-medium">站点信息加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ loadError }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <template v-else>
      <ConsoleSection title="品牌信息">
        <div class="space-y-4">
          <label class="block space-y-1.5">
            <span class="text-[12.5px] font-medium">站点名称</span>
            <Input v-model="name" maxlength="64" placeholder="例如 PigeonAgent" />
          </label>

          <label class="block space-y-1.5">
            <span class="text-[12.5px] font-medium">站点简介</span>
            <Input v-model="description" maxlength="500" placeholder="一句话介绍这个站点" />
          </label>

          <div class="space-y-2">
            <span class="text-[12.5px] font-medium">站点 Logo</span>
            <div class="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-background p-4">
              <div class="grid size-16 shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-card">
                <img
                  v-if="previewSrc"
                  :src="previewSrc"
                  alt="站点 Logo 预览"
                  class="size-full object-contain"
                >
                <BrandMark v-else size="lg" />
              </div>
              <div class="min-w-0 flex-1">
                <p class="text-sm text-muted-foreground">
                  建议使用正方形 PNG/WebP，小于 2 MB；会公开显示，不要放敏感内容。
                </p>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <input
                    ref="fileInput"
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    class="hidden"
                    @change="onLogoFile"
                  >
                  <Button type="button" variant="outline" class="h-8" :disabled="uploading" @click="pickLogo">
                    <Loader2 v-if="uploading" class="size-3.5 animate-spin" />
                    <ImagePlus v-else class="size-3.5" />
                    {{ logoUrl ? '更换 Logo' : '上传 Logo' }}
                  </Button>
                  <template v-if="logoUrl">
                    <Button
                      type="button"
                      variant="ghost"
                      class="h-8 text-muted-foreground hover:text-destructive"
                      :disabled="removing"
                      @click="removeLogo"
                    >
                      <Trash2 class="size-3.5" />
                      {{ confirmRemove ? '确认移除' : '移除' }}
                    </Button>
                    <Button
                      v-if="confirmRemove"
                      type="button"
                      variant="ghost"
                      class="h-8 text-muted-foreground"
                      :disabled="removing"
                      @click="confirmRemove = false"
                    >
                      取消
                    </Button>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </ConsoleSection>

      <div class="flex justify-end">
        <Button :disabled="saving" @click="save">
          <Loader2 v-if="saving" class="size-4 animate-spin" />
          {{ saving ? '保存中' : '保存站点信息' }}
        </Button>
      </div>
    </template>
  </div>
</template>
