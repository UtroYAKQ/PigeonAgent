<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { Archive, ArchiveRestore, Loader2, MessagesSquare, RefreshCw } from '@lucide/vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import AdminPager from '@/components/admin/AdminPager.vue'
import TableFrame from '@/components/console/TableFrame.vue'
import { adminApi } from '@/api/admin'
import { usePagedTable } from '@/composables/usePagedTable'
import { formatAdminTime } from '@/lib/admin'
import { formatRelativeTime, formatTokens } from '@/lib/format'
import { errorMessage } from '@/lib/http'
import type { AdminSession, SessionStatus } from '@/types/api'

const STATUS_LABELS: Record<SessionStatus, string> = {
  active: '活跃',
  archived: '已归档',
}

const query = ref('')
const statusFilter = ref<SessionStatus | 'all'>('all')
const updatingId = ref<string | null>(null)
const {
  items: sessions,
  total,
  loading,
  error,
  offset,
  limit,
  rangeLabel,
  load,
  page,
} = usePagedTable<AdminSession>({
  limit: 20,
  fetchPage: params => adminApi.sessions({
    q: query.value.trim() || undefined,
    status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    ...params,
  }),
})

const search = useDebounceFn(() => load(true), 300)
watch(query, search)
watch(statusFilter, () => load(true))
onMounted(() => load(true))

function cacheLabel(session: AdminSession): string {
  const read = session.usage.cache_read_tokens
  return read ? `缓存命中 ${formatTokens(read)}` : ''
}

async function toggleStatus(session: AdminSession): Promise<void> {
  if (updatingId.value) return
  if (session.status === 'active' && session.active_run_id) {
    toast.error('运行中的会话不能归档')
    return
  }
  const next: SessionStatus = session.status === 'archived' ? 'active' : 'archived'
  updatingId.value = session.id
  try {
    const updated = await adminApi.updateSession(session.id, next)
    sessions.value = sessions.value.map(item => (item.id === updated.id ? updated : item))
    toast.success(next === 'archived' ? '会话已归档' : '会话已恢复')
  } catch (caught) {
    toast.error('操作失败', { description: errorMessage(caught) })
  } finally {
    updatingId.value = null
  }
}
</script>

<template>
  <div>
    <TableFrame>
      <template #toolbar>
        <Input
          v-model="query"
          placeholder="搜索标题或所有者"
          class="h-8 w-[260px] max-w-full text-[13px]"
        />
        <Select v-model="statusFilter">
          <SelectTrigger class="h-8 w-[120px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem value="all" class="text-[13px]">全部状态</SelectItem>
            <SelectItem value="active" class="text-[13px]">活跃</SelectItem>
            <SelectItem value="archived" class="text-[13px]">已归档</SelectItem>
          </SelectContent>
        </Select>
        <span class="flex-1" />
        <Button variant="outline" class="h-8" :disabled="loading" @click="load()">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </template>

      <Table class="min-w-[1060px] text-[13px]">
        <TableHeader>
          <TableRow>
            <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">会话</TableHead>
            <TableHead class="h-9 w-[220px] px-4 text-[11px] font-medium text-muted-foreground">所有者</TableHead>
            <TableHead class="h-9 w-[160px] px-4 text-[11px] font-medium text-muted-foreground">状态</TableHead>
            <TableHead class="h-9 w-[150px] px-4 text-[11px] font-medium text-muted-foreground">活动</TableHead>
            <TableHead class="h-9 w-[120px] px-4 text-[11px] font-medium text-muted-foreground">最后活跃</TableHead>
            <TableHead class="h-9 w-[160px] px-4 text-[11px] font-medium text-muted-foreground">创建时间</TableHead>
            <TableHead class="h-9 w-[96px] px-4 text-right text-[11px] font-medium text-muted-foreground">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template v-if="loading && !sessions.length">
            <TableRow v-for="index in 5" :key="index" class="hover:bg-transparent">
              <TableCell class="px-4 py-2.5">
                <div class="space-y-2">
                  <div class="h-3 w-44 animate-pulse rounded-full bg-muted" />
                  <div class="h-2.5 w-20 animate-pulse rounded-full bg-muted" />
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <div class="space-y-2">
                  <div class="h-3 w-24 animate-pulse rounded-full bg-muted" />
                  <div class="h-2.5 w-36 animate-pulse rounded-full bg-muted" />
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-5 w-16 animate-pulse rounded-md bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-16 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-20 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-24 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="ml-auto h-8 w-20 animate-pulse rounded-md bg-muted" /></TableCell>
            </TableRow>
          </template>

          <TableRow v-else-if="error" class="hover:bg-transparent">
            <TableCell colspan="7" class="px-4 py-12 text-center">
              <p class="text-sm font-medium">会话加载失败</p>
              <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ error }}</p>
              <Button variant="outline" class="mt-4 h-9" @click="load()">
                <RefreshCw class="size-4" />
                重试
              </Button>
            </TableCell>
          </TableRow>

          <TableRow v-else-if="!sessions.length" class="hover:bg-transparent">
            <TableCell colspan="7" class="px-4 py-14 text-center">
              <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
                <MessagesSquare class="size-4" />
              </span>
              <p class="mt-4 text-sm font-medium">{{ query || statusFilter !== 'all' ? '没有匹配的会话' : '还没有会话' }}</p>
              <p class="mt-1 text-sm text-muted-foreground">
                {{ query || statusFilter !== 'all' ? '调整搜索词或状态筛选试试。' : '用户开始对话后会出现在这里。' }}
              </p>
            </TableCell>
          </TableRow>

          <template v-else>
            <TableRow v-for="session in sessions" :key="session.id">
              <TableCell class="px-4 py-2.5">
                <p class="max-w-[220px] truncate text-sm font-medium sm:max-w-[360px]">{{ session.title || '未命名会话' }}</p>
                <p class="max-w-[220px] truncate font-mono text-[11px] text-muted-foreground sm:max-w-[360px]">
                  {{ session.id.slice(0, 8) }}
                </p>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <p class="max-w-[190px] truncate text-sm">{{ session.owner_display_name || session.owner_email || '未知用户' }}</p>
                <p v-if="session.owner_email" class="max-w-[190px] truncate text-xs text-muted-foreground" :title="session.owner_email">{{ session.owner_email }}</p>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <div class="flex flex-wrap items-center gap-2">
                  <Badge :variant="session.status === 'active' ? 'secondary' : 'outline'">
                    {{ STATUS_LABELS[session.status] }}
                  </Badge>
                  <Badge v-if="session.active_run_id" variant="outline" class="gap-1.5">
                    <span class="size-1.5 animate-pulse rounded-full bg-primary" />
                    运行中
                  </Badge>
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <p class="text-sm tabular-nums">{{ session.run_count }} 轮</p>
                <p class="text-xs tabular-nums text-muted-foreground">{{ formatTokens(session.usage.total_tokens) }} tokens</p>
                <p v-if="cacheLabel(session)" class="text-[11px] tabular-nums text-muted-foreground">{{ cacheLabel(session) }}</p>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-sm text-muted-foreground">
                <span :title="formatAdminTime(session.last_run_at)">
                  {{ formatRelativeTime(session.last_run_at) }}
                </span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-sm text-muted-foreground">
                <span :title="formatAdminTime(session.created_at)">{{ formatAdminTime(session.created_at) }}</span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-right">
                <Button
                  variant="outline"
                  class="h-7"
                  :disabled="updatingId === session.id || (session.status === 'active' && Boolean(session.active_run_id))"
                  :title="session.status === 'active' && session.active_run_id ? '运行中的会话不能归档' : undefined"
                  @click="toggleStatus(session)"
                >
                  <Loader2 v-if="updatingId === session.id" class="size-4 animate-spin" />
                  <ArchiveRestore v-else-if="session.status === 'archived'" class="size-4" />
                  <Archive v-else class="size-4" />
                  {{ session.status === 'archived' ? '恢复' : '归档' }}
                </Button>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>

      <template #footer>
        <p class="hidden text-xs text-muted-foreground sm:block">运行中的会话不能归档</p>
        <div class="ml-auto flex flex-wrap items-center gap-4">
          <p class="text-xs tabular-nums text-muted-foreground">共 {{ total }} 个会话 · {{ rangeLabel }}</p>
          <AdminPager :offset="offset" :limit="limit" :total="total" @page="page" />
        </div>
      </template>
    </TableFrame>
  </div>
</template>
