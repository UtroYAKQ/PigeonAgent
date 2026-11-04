<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Coins, RefreshCw } from '@lucide/vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import AdminPager from '@/components/admin/AdminPager.vue'
import TableFrame from '@/components/console/TableFrame.vue'
import { adminApi } from '@/api/admin'
import { usePagedTable } from '@/composables/usePagedTable'
import { formatAdminTime } from '@/lib/admin'
import { formatCredits, formatMessageTime, formatTokens } from '@/lib/format'
import type { AdminChatLog, AdminCreditLog } from '@/types/api'

type Tab = 'chats' | 'credits'

const CHAT_STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'completed', label: '已完成' },
  { value: 'interrupted', label: '待恢复' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const REASON_OPTIONS = [
  { value: 'all', label: '全部类型' },
  { value: 'chat', label: '对话' },
  { value: 'image', label: '出图' },
  { value: 'adjust', label: '人工调整' },
]

const REASON_LABELS: Record<string, string> = {
  chat: '对话',
  image: '出图',
  adjust: '调整',
}

// 两张表同一页大小：取数和页脚翻页控件共用一个步长
const PAGE_LIMIT = 30

const tab = ref<Tab>('chats')
const chatStatusFilter = ref('all')
const creditReasonFilter = ref('all')

const {
  items: chatLogs,
  total: chatTotal,
  loading: chatLoading,
  error: chatError,
  loaded: chatLoaded,
  offset: chatOffset,
  rangeLabel: chatRangeLabel,
  load: loadChats,
  page: chatPage,
} = usePagedTable<AdminChatLog>({
  limit: PAGE_LIMIT,
  fetchPage: params => adminApi.chatLogs({
    status: chatStatusFilter.value === 'all' ? undefined : chatStatusFilter.value,
    ...params,
  }),
})

const {
  items: creditLogs,
  total: creditTotal,
  loading: creditLoading,
  error: creditError,
  loaded: creditLoaded,
  offset: creditOffset,
  rangeLabel: creditRangeLabel,
  load: loadCredits,
  page: creditPage,
} = usePagedTable<AdminCreditLog>({
  limit: PAGE_LIMIT,
  fetchPage: params => adminApi.creditLogs({
    reason: creditReasonFilter.value === 'all' ? undefined : creditReasonFilter.value,
    ...params,
  }),
})

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  interrupted: '待恢复',
  failed: '失败',
  cancelled: '已取消',
  running: '运行中',
}

/** 对话轮次的状态芯片配色，和 HTTP 状态码那套是两回事 */
function chatStatusChip(status: string): string {
  if (status === 'completed') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
  if (status === 'failed') return 'border-destructive/30 bg-destructive/10 text-destructive'
  if (status === 'interrupted') return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400'
  return 'border-border bg-muted text-muted-foreground'
}

function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason
}

function deltaTone(delta: number): string {
  if (delta > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (delta < 0) return 'text-destructive'
  return 'text-muted-foreground'
}

function tokensOf(log: AdminChatLog): string {
  const usage = log.usage
  if (!usage || !usage.total_tokens) return '—'
  return usage.total_tokens.toLocaleString()
}

function cacheOf(log: AdminChatLog): string {
  const read = log.usage?.cache_read_tokens ?? 0
  return read ? `缓存命中 ${formatTokens(read)}` : ''
}

function loadCurrent(reset = false): void {
  if (tab.value === 'chats') void loadChats(reset)
  else void loadCredits(reset)
}

function switchTab(value: string | number): void {
  tab.value = value as Tab
  const loaded = tab.value === 'chats' ? chatLoaded.value : creditLoaded.value
  if (!loaded) loadCurrent(true)
}

onMounted(() => loadCurrent(true))
</script>

<template>
  <div>
    <TableFrame>
      <template #toolbar>
        <Tabs :model-value="tab" @update:model-value="switchTab">
          <TabsList class="h-8">
            <TabsTrigger value="chats" class="px-3 text-xs">聊天记录</TabsTrigger>
            <TabsTrigger value="credits" class="px-3 text-xs">积分流水</TabsTrigger>
          </TabsList>
        </Tabs>
        <Select
          v-if="tab === 'chats'"
          :model-value="chatStatusFilter"
          @update:model-value="chatStatusFilter = String($event); loadCurrent(true)"
        >
          <SelectTrigger class="h-8 w-[116px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem
              v-for="option in CHAT_STATUS_OPTIONS"
              :key="option.value"
              :value="option.value"
              class="text-[13px]"
            >
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select
          v-else
          :model-value="creditReasonFilter"
          @update:model-value="creditReasonFilter = String($event); loadCurrent(true)"
        >
          <SelectTrigger class="h-8 w-[116px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem
              v-for="option in REASON_OPTIONS"
              :key="option.value"
              :value="option.value"
              class="text-[13px]"
            >
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="flex-1" />
        <Button variant="outline" class="h-8" :disabled="tab === 'chats' ? chatLoading : creditLoading" @click="loadCurrent()">
          <RefreshCw class="size-3.5" :class="(tab === 'chats' ? chatLoading : creditLoading) ? 'animate-spin' : ''" />
          刷新
        </Button>
      </template>

      <Tabs :model-value="tab" class="contents" @update:model-value="switchTab">
        <TabsContent value="chats" class="mt-0">
          <Table class="min-w-[860px] text-[13px]">
            <TableHeader>
              <TableRow>
                <TableHead class="h-9 w-[104px] px-4 text-[11px] font-medium text-muted-foreground">时间</TableHead>
                <TableHead class="h-9 w-[190px] px-4 text-[11px] font-medium text-muted-foreground">用户</TableHead>
                <TableHead class="h-9 min-w-[160px] px-4 text-[11px] font-medium text-muted-foreground">模型</TableHead>
                <TableHead class="h-9 w-[110px] px-4 text-right text-[11px] font-medium text-muted-foreground">Token</TableHead>
                <TableHead class="h-9 w-[64px] px-4 text-right text-[11px] font-medium text-muted-foreground">图片</TableHead>
                <TableHead class="h-9 w-[88px] px-4 text-right text-[11px] font-medium text-muted-foreground">积分</TableHead>
                <TableHead class="h-9 w-[88px] px-4 text-[11px] font-medium text-muted-foreground">状态</TableHead>
                <TableHead class="h-9 w-[80px] px-4 text-right text-[11px] font-medium text-muted-foreground">耗时</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <template v-if="chatLoading && !chatLogs.length">
                <TableRow v-for="index in 6" :key="index" class="hover:bg-transparent">
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-16 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-36 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-28 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-14 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-6 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-5 w-12 animate-pulse rounded-md bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5" />
                </TableRow>
              </template>

              <TableRow v-else-if="chatError" class="hover:bg-transparent">
                <TableCell colspan="8" class="px-4 py-12 text-center">
                  <p class="text-sm font-medium">聊天记录加载失败</p>
                  <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ chatError }}</p>
                  <Button variant="outline" class="mt-4 h-9" @click="loadCurrent()">
                    <RefreshCw class="size-4" />
                    重试
                  </Button>
                </TableCell>
              </TableRow>

              <TableRow v-else-if="!chatLogs.length" class="hover:bg-transparent">
                <TableCell colspan="8" class="px-4 py-14 text-center">
                  <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
                    <Coins class="size-4" />
                  </span>
                  <p class="mt-4 text-sm font-medium">还没有对话记录</p>
                  <p class="mt-1 text-sm text-muted-foreground">每轮对话结束后会在这里留下用量与扣分。</p>
                </TableCell>
              </TableRow>

              <template v-else>
                <TableRow v-for="log in chatLogs" :key="log.id">
                  <TableCell class="px-4 py-2.5 text-xs text-muted-foreground">
                    <span :title="formatAdminTime(log.created_at)">{{ formatMessageTime(log.created_at) }}</span>
                  </TableCell>
                  <TableCell class="max-w-[190px] px-4 py-2.5 text-xs">
                    <p v-if="log.user_display_name" class="truncate text-foreground">{{ log.user_display_name }}</p>
                    <p class="truncate text-[11px] text-muted-foreground">{{ log.user_email || '匿名' }}</p>
                  </TableCell>
                  <TableCell class="px-4 py-2.5">
                    <div class="flex min-w-0 items-center gap-2">
                      <span class="truncate text-xs">{{ log.model_name || '—' }}</span>
                      <Badge v-if="log.kind === 'resume'" variant="outline" class="shrink-0 font-normal text-[10px]">恢复</Badge>
                    </div>
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs tabular-nums">
                    <div>{{ tokensOf(log) }}</div>
                    <div v-if="cacheOf(log)" class="text-[10.5px] font-normal text-muted-foreground">{{ cacheOf(log) }}</div>
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {{ log.images_generated || '—' }}
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs tabular-nums" :class="log.credits_charged ? '' : 'text-muted-foreground'">
                    {{ log.credits_charged > 0 ? `-${formatCredits(log.credits_charged)}` : '—' }}
                  </TableCell>
                  <TableCell class="px-4 py-2.5">
                    <span
                      class="inline-flex h-6 items-center rounded-md border px-1.5 text-[11px]"
                      :class="chatStatusChip(log.status)"
                      :title="log.error || undefined"
                    >
                      {{ STATUS_LABELS[log.status] ?? log.status }}
                    </span>
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs text-muted-foreground">
                    {{ log.duration_ms != null ? `${(log.duration_ms / 1000).toFixed(1)}s` : '—' }}
                  </TableCell>
                </TableRow>
              </template>
            </TableBody>
          </Table>
        </TabsContent>

        <TabsContent value="credits" class="mt-0">
          <Table class="min-w-[760px] text-[13px]">
            <TableHeader>
              <TableRow>
                <TableHead class="h-9 w-[104px] px-4 text-[11px] font-medium text-muted-foreground">时间</TableHead>
                <TableHead class="h-9 w-[190px] px-4 text-[11px] font-medium text-muted-foreground">用户</TableHead>
                <TableHead class="h-9 w-[88px] px-4 text-[11px] font-medium text-muted-foreground">类型</TableHead>
                <TableHead class="h-9 w-[110px] px-4 text-right text-[11px] font-medium text-muted-foreground">变动</TableHead>
                <TableHead class="h-9 w-[110px] px-4 text-right text-[11px] font-medium text-muted-foreground">余额</TableHead>
                <TableHead class="h-9 min-w-[200px] px-4 text-[11px] font-medium text-muted-foreground">说明</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <template v-if="creditLoading && !creditLogs.length">
                <TableRow v-for="index in 6" :key="index" class="hover:bg-transparent">
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-16 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-36 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-5 w-12 animate-pulse rounded-md bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
                  <TableCell class="px-4 py-2.5"><div class="h-3 w-40 animate-pulse rounded-full bg-muted" /></TableCell>
                </TableRow>
              </template>

              <TableRow v-else-if="creditError" class="hover:bg-transparent">
                <TableCell colspan="6" class="px-4 py-12 text-center">
                  <p class="text-sm font-medium">积分流水加载失败</p>
                  <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ creditError }}</p>
                  <Button variant="outline" class="mt-4 h-9" @click="loadCurrent()">
                    <RefreshCw class="size-4" />
                    重试
                  </Button>
                </TableCell>
              </TableRow>

              <TableRow v-else-if="!creditLogs.length" class="hover:bg-transparent">
                <TableCell colspan="6" class="px-4 py-14 text-center">
                  <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
                    <Coins class="size-4" />
                  </span>
                  <p class="mt-4 text-sm font-medium">还没有积分流水</p>
                  <p class="mt-1 text-sm text-muted-foreground">充值、对话扣分和出图扣分都会记在这里。</p>
                </TableCell>
              </TableRow>

              <template v-else>
                <TableRow v-for="log in creditLogs" :key="log.id">
                  <TableCell class="px-4 py-2.5 text-xs text-muted-foreground">
                    <span :title="formatAdminTime(log.created_at)">{{ formatMessageTime(log.created_at) }}</span>
                  </TableCell>
                  <TableCell class="max-w-[190px] px-4 py-2.5 text-xs">
                    <p v-if="log.user_display_name" class="truncate text-foreground">{{ log.user_display_name }}</p>
                    <p class="truncate text-[11px] text-muted-foreground">{{ log.user_email || '已删除用户' }}</p>
                  </TableCell>
                  <TableCell class="px-4 py-2.5">
                    <Badge variant="outline" class="font-normal">{{ reasonLabel(log.reason) }}</Badge>
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs tabular-nums" :class="deltaTone(log.delta)">
                    {{ log.delta > 0 ? `+${log.delta}` : log.delta }}
                  </TableCell>
                  <TableCell class="px-4 py-2.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {{ formatCredits(log.balance_after) }}
                  </TableCell>
                  <TableCell class="max-w-[320px] truncate px-4 py-2.5 text-xs text-muted-foreground">
                    <template v-if="log.note">{{ log.note }}</template>
                    <template v-else-if="log.reason === 'chat' && log.usage?.total_tokens">
                      {{ log.usage.total_tokens.toLocaleString() }} tokens
                      <template v-if="log.usage.cache_read_tokens">
                        · 缓存命中 {{ formatTokens(log.usage.cache_read_tokens) }}
                      </template>
                    </template>
                    <template v-else-if="log.reason === 'image' && log.usage?.images">
                      {{ log.usage.images }} 张图片
                    </template>
                    <template v-else>—</template>
                  </TableCell>
                </TableRow>
              </template>
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>

      <template #footer>
        <p class="hidden text-xs text-muted-foreground sm:block">
          {{ tab === 'chats' ? '每轮对话的用量与扣分快照' : '账本只增不改，余额以最新一条为准' }}
        </p>
        <div class="ml-auto flex flex-wrap items-center gap-4">
          <p class="text-xs tabular-nums text-muted-foreground">
            共 {{ tab === 'chats' ? chatTotal : creditTotal }} 条记录 ·
            {{ tab === 'chats' ? chatRangeLabel : creditRangeLabel }}
          </p>
          <AdminPager
            v-if="tab === 'chats'"
            :offset="chatOffset"
            :limit="PAGE_LIMIT"
            :total="chatTotal"
            @page="chatPage"
          />
          <AdminPager
            v-else
            :offset="creditOffset"
            :limit="PAGE_LIMIT"
            :total="creditTotal"
            @page="creditPage"
          />
        </div>
      </template>
    </TableFrame>
  </div>
</template>
