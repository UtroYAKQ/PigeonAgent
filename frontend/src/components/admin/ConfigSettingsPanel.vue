<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Loader2, RefreshCw } from '@lucide/vue'

import ConfigField from '@/components/admin/ConfigField.vue'
import { CONFIG_GROUP_LAYOUT, type AdminConfigCategory } from '@/components/admin/config'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Button } from '@/components/ui/button'
import { configsApi } from '@/api/configs'
import { errorMessage } from '@/lib/http'
import type { AppConfigItem } from '@/types/api'

const props = defineProps<{ category: AdminConfigCategory }>()

const items = ref<AppConfigItem[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)
const saving = ref(false)
// 数字输入框会写回 number，所以草稿不能只当字符串；比较和提交前统一转字符串
const drafts = reactive<Record<string, string | number>>({})
const originals = reactive<Record<string, string | number>>({})

const activeItems = computed(() =>
  items.value.filter(item => item.category === props.category),
)
const activeGroups = computed(() => {
  const layout = CONFIG_GROUP_LAYOUT[props.category] ?? []
  const byKey = new Map(activeItems.value.map(item => [item.key, item]))
  const used = new Set<string>()
  const groups: { title: string; items: AppConfigItem[] }[] = []
  for (const group of layout) {
    const groupItems = group.keys
      .map(key => byKey.get(key))
      .filter((item): item is AppConfigItem => Boolean(item))
    if (!groupItems.length) continue
    groups.push({ title: group.title, items: groupItems })
    for (const item of groupItems) used.add(item.key)
  }
  const remaining = activeItems.value.filter(item => !used.has(item.key))
  if (remaining.length) groups.push({ title: '其他', items: remaining })
  return groups
})

function isDirty(item: AppConfigItem): boolean {
  // 原值永远是字符串，草稿可能是 number，不归一的话填同样的端口也会一直显示未保存
  return String(drafts[item.key] ?? '') !== String(originals[item.key] ?? '')
}

const dirtyItems = computed(() => activeItems.value.filter(item => isDirty(item)))
const dirtyCount = computed(() => dirtyItems.value.length)

function syncDrafts(): void {
  for (const item of items.value) {
    const initial = item.is_secret ? '' : (item.value ?? '')
    drafts[item.key] = initial
    originals[item.key] = initial
  }
}

function replaceItem(updated: AppConfigItem): void {
  items.value = items.value.map(item => (item.key === updated.key ? updated : item))
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const data = await configsApi.list()
    items.value = data.items
    syncDrafts()
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  const pending = [...dirtyItems.value]
  if (!pending.length) return

  saving.value = true
  const failures: string[] = []
  for (const item of pending) {
    try {
      const updated = await configsApi.update(item.key, String(drafts[item.key] ?? ''))
      replaceItem(updated)
      const next = updated.is_secret ? '' : (updated.value ?? '')
      drafts[updated.key] = next
      originals[updated.key] = next
    } catch (error) {
      failures.push(`${item.label}：${errorMessage(error)}`)
    }
  }
  saving.value = false

  if (failures.length) {
    toast.error('部分配置没有保存', { description: failures[0] })
    return
  }
  toast.success('配置已保存')
}

function discardChanges(): void {
  for (const item of activeItems.value) {
    drafts[item.key] = originals[item.key]
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">
        共 <span class="tabular-nums">{{ activeItems.length }}</span> 项配置
      </p>
      <Button
        variant="outline"
        class="h-9"
        :disabled="loading || saving || dirtyCount > 0"
        @click="load"
      >
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <div v-if="loading" class="space-y-3">
      <div v-for="index in 4" :key="index" class="space-y-2">
        <div class="h-3 w-28 animate-pulse rounded-full bg-muted" />
        <div class="h-3 w-2/3 animate-pulse rounded-full bg-muted" />
      </div>
    </div>

    <div
      v-else-if="loadError"
      class="rounded-lg border border-border bg-card px-4 py-16 text-center"
    >
      <p class="text-sm font-medium">配置加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ loadError }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <form v-else @submit.prevent="save" class="space-y-8">
      <ConsoleSection
        v-for="group in activeGroups"
        :key="group.title"
        :title="group.title"
      >
        <ConfigField
          v-for="item in group.items"
          :key="item.key"
          :item="item"
          v-model="drafts[item.key]"
        />
      </ConsoleSection>

      <div
        v-if="!activeGroups.length"
        class="rounded-lg border border-border bg-card px-4 py-16 text-center text-sm text-muted-foreground"
      >
        这一组还没有可配置项
      </div>

      <div
        v-if="activeItems.length"
        class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-background px-4 py-2.5"
      >
        <p class="text-sm text-muted-foreground">
          {{ dirtyCount ? `${dirtyCount} 项更改未保存` : '所有更改已保存' }}
        </p>
        <div class="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            class="h-9 text-muted-foreground"
            :disabled="!dirtyCount || saving"
            @click="discardChanges"
          >
            撤销
          </Button>
          <Button
            type="submit"
            class="h-9"
            :disabled="!dirtyCount || saving"
          >
            <Loader2 v-if="saving" class="size-4 animate-spin" />
            {{ saving ? '保存中' : '保存更改' }}
          </Button>
        </div>
      </div>
    </form>
  </div>
</template>
