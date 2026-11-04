<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Check, Copy, Link2, RefreshCw, ShieldOff } from '@lucide/vue'

import { sharesApi } from '@/api/shares'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Button } from '@/components/ui/button'
import { TooltipHint } from '@/components/ui/tooltip'
import { copyToClipboard } from '@/lib/clipboard'
import { formatDateTime, formatRelativeTime } from '@/lib/format'
import { errorMessage } from '@/lib/http'
import type { SessionShare } from '@/types/api'

const shares = ref<SessionShare[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const copiedId = ref<string | null>(null)
const pendingRevokeId = ref<string | null>(null)

function linkOf(share: SessionShare): string {
  return `${window.location.origin}/s/${share.token}`
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    shares.value = await sharesApi.list()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function copy(share: SessionShare): Promise<void> {
  if (await copyToClipboard(linkOf(share))) {
    copiedId.value = share.id
    window.setTimeout(() => {
      if (copiedId.value === share.id) copiedId.value = null
    }, 1_600)
    return
  }
  toast.error('复制失败', { description: '浏览器拒绝了剪贴板访问，请手动选中链接复制' })
}

// 撤销只影响这一条链接：点第一次先要求确认，再点才真的撤
async function revoke(share: SessionShare): Promise<void> {
  if (pendingRevokeId.value !== share.id) {
    pendingRevokeId.value = share.id
    return
  }
  try {
    await sharesApi.revoke(share.id)
    shares.value = shares.value.filter(item => item.id !== share.id)
    pendingRevokeId.value = null
    toast.success('链接已撤销')
  } catch (caught) {
    toast.error('撤销失败', { description: errorMessage(caught) })
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="space-y-3 pt-3">
    <ConsoleSection
      title="有效的分享链接"
      description="到期后自动失效，也可以随时撤销；撤销只影响这一条链接。"
    >
      <div class="flex items-center justify-between gap-3">
        <p class="text-[12.5px] text-muted-foreground">
          {{ loading ? '加载中…' : `${shares.length} 条有效链接` }}
        </p>
        <Button variant="outline" class="h-8" :disabled="loading" @click="refresh">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>

      <div v-if="loading" class="mt-3 space-y-2">
        <div v-for="index in 2" :key="index" class="h-14 animate-pulse rounded-lg bg-muted/40" />
      </div>

      <div v-else-if="error" class="mt-3 rounded-lg border border-destructive/20 px-4 py-3">
        <p class="text-[13px] font-medium text-destructive">链接读取失败</p>
        <p class="mt-1 text-[12.5px] leading-5 text-muted-foreground">{{ error }}</p>
      </div>

      <div v-else-if="!shares.length" class="mt-3 rounded-lg border border-dashed px-4 py-8 text-center">
        <Link2 class="mx-auto size-4 text-muted-foreground" :stroke-width="1.8" />
        <p class="mt-2.5 text-[13px] font-medium">还没有分享链接</p>
        <p class="mt-1 text-[12.5px] leading-5 text-muted-foreground">
          在对话标题栏点分享图标，即可为当前对话生成只读链接。
        </p>
      </div>

      <ul v-else class="mt-3 divide-y divide-border">
        <li v-for="share in shares" :key="share.id" class="flex items-center gap-3 py-3">
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13px] font-medium">
              {{ share.session_title || '未命名对话' }}
            </span>
            <span class="mt-1 block text-[12px] leading-5 text-muted-foreground">
              {{ formatDateTime(share.expires_at) }} 到期 ·
              已访问 {{ share.visit_count }} 次{{ share.last_visited_at
                ? `（最近 ${formatRelativeTime(share.last_visited_at)}）` : '' }}
            </span>
          </span>
          <Button variant="outline" class="h-8 shrink-0" @click="copy(share)">
            <Check v-if="copiedId === share.id" class="size-3.5" />
            <Copy v-else class="size-3.5" />
            <span>{{ copiedId === share.id ? '已复制' : '复制链接' }}</span>
          </Button>
          <TooltipHint text="撤销后这条链接立刻打不开，其他链接不受影响">
            <Button
              :variant="pendingRevokeId === share.id ? 'default' : 'outline'"
              class="h-8 shrink-0"
              @click="revoke(share)"
            >
              <ShieldOff class="size-3.5" />
              <span>{{ pendingRevokeId === share.id ? '确认撤销' : '撤销' }}</span>
            </Button>
          </TooltipHint>
        </li>
      </ul>
    </ConsoleSection>
  </div>
</template>
