<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { Eye, RefreshCw, ScrollText } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import AdminPager from '@/components/admin/AdminPager.vue'
import { CodeBlock } from '@/components/ai-elements/code-block'
import TableFrame from '@/components/console/TableFrame.vue'
import ToolCodeCopy from '@/components/chat/ToolCodeCopy.vue'
import { adminApi } from '@/api/admin'
import { usePagedTable } from '@/composables/usePagedTable'
import {
  AUDIT_ACTION_OPTIONS,
  auditActionIcon,
  auditActionLabel,
  formatAdminTime,
} from '@/lib/admin'
import { formatMessageTime } from '@/lib/format'
import type { AdminOperationLog } from '@/types/api'

const METHOD_OPTIONS = ['all', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const KIND_OPTIONS = [
  { value: 'all', label: '全部记录' },
  { value: 'request', label: 'HTTP 请求' },
  { value: 'admin', label: '管理操作' },
]

const query = ref('')
const methodFilter = ref('all')
const kindFilter = ref('all')
const actionFilter = ref('all')
const {
  items: logs,
  total,
  loading,
  error,
  offset,
  limit,
  rangeLabel,
  load,
  page,
} = usePagedTable<AdminOperationLog>({
  limit: 30,
  fetchPage: params => adminApi.logs({
    q: query.value.trim() || undefined,
    method: methodFilter.value === 'all' ? undefined : methodFilter.value,
    kind: kindFilter.value === 'all' ? undefined : (kindFilter.value as 'request' | 'admin'),
    action: actionFilter.value === 'all' ? undefined : actionFilter.value,
    ...params,
  }),
})

const detailOpen = ref(false)
const activeLog = ref<AdminOperationLog | null>(null)
const detailTab = ref<'request' | 'response' | 'admin'>('request')

const activeTitle = computed(() =>
  activeLog.value ? operationLabel(activeLog.value) : '操作详情',
)
const requestJson = computed(() =>
  activeLog.value
    ? formatJson({
        query: activeLog.value.query,
        body: activeLog.value.request_body,
        truncated: activeLog.value.request_truncated,
      })
    : '',
)
const responseJson = computed(() =>
  activeLog.value
    ? formatJson({
        body: activeLog.value.response_body,
        truncated: activeLog.value.response_truncated,
      })
    : '',
)
const adminJson = computed(() =>
  activeLog.value?.action
    ? formatJson({
        action: activeLog.value.action,
        target_type: activeLog.value.target_type,
        target_id: activeLog.value.target_id,
        detail: activeLog.value.detail,
      })
    : '',
)
const activeCode = computed(() => {
  if (detailTab.value === 'response') return responseJson.value
  if (detailTab.value === 'admin') return adminJson.value
  return requestJson.value
})
const activeTruncated = computed(() => {
  if (!activeLog.value) return false
  if (detailTab.value === 'request') return activeLog.value.request_truncated
  if (detailTab.value === 'response') return activeLog.value.response_truncated
  return false
})

const search = useDebounceFn(() => load(true), 300)
watch(query, search)
watch([methodFilter, kindFilter, actionFilter], () => load(true))
onMounted(() => load(true))

function openDetail(log: AdminOperationLog): void {
  activeLog.value = log
  detailTab.value = 'request'
  detailOpen.value = true
}

function operationLabel(log: AdminOperationLog): string {
  if (log.action) return auditActionLabel(log.action)
  return `${log.method || 'HTTP'} ${log.route || log.path || ''}`.trim()
}

/** 按 HTTP 状态码分级上色：5xx 红、4xx 黄，其余中性 */
function httpStatusTone(status: number | null): string {
  if (status == null) return 'border-border text-muted-foreground'
  if (status >= 500) return 'border-destructive/30 bg-destructive/10 text-destructive'
  if (status >= 400) return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400'
  return 'border-border text-foreground'
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? ''
}

// 三张 JSON 视图共用：外层撑满标签页，内部滚动，字号与原来的纯文本一致
const JSON_VIEW_CLASS = 'min-h-0 flex-1 overflow-hidden rounded-md border-border bg-code [&>div]:h-full [&_pre]:p-3! [&_pre]:text-[11px]! [&_pre]:leading-5 [&_code]:text-[11px]!'
</script>

<template>
  <div>
    <TableFrame>
      <template #toolbar>
        <Input
          v-model="query"
          placeholder="搜索用户、路径或 request id"
          class="h-8 w-[250px] max-w-full text-[13px]"
        />
        <Select v-model="kindFilter">
          <SelectTrigger class="h-8 w-[120px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem v-for="option in KIND_OPTIONS" :key="option.value" :value="option.value" class="text-[13px]">
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="methodFilter">
          <SelectTrigger class="h-8 w-[108px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem v-for="method in METHOD_OPTIONS" :key="method" :value="method" class="text-[13px]">
              {{ method === 'all' ? '全部方法' : method }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="actionFilter">
          <SelectTrigger class="h-8 w-[116px] text-[13px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem v-for="option in AUDIT_ACTION_OPTIONS" :key="option.value" :value="option.value" class="text-[13px]">
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="flex-1" />
        <Button variant="outline" class="h-8" :disabled="loading" @click="load()">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </template>

      <Table class="min-w-[900px] text-[13px]">
        <TableHeader>
          <TableRow>
            <TableHead class="h-9 w-[104px] px-4 text-[11px] font-medium text-muted-foreground">时间</TableHead>
            <TableHead class="h-9 w-[190px] px-4 text-[11px] font-medium text-muted-foreground">用户</TableHead>
            <TableHead class="h-9 min-w-[260px] px-4 text-[11px] font-medium text-muted-foreground">请求</TableHead>
            <TableHead class="h-9 w-[80px] px-4 text-[11px] font-medium text-muted-foreground">状态</TableHead>
            <TableHead class="h-9 w-[80px] px-4 text-[11px] font-medium text-muted-foreground">耗时</TableHead>
            <TableHead class="h-9 w-[150px] px-4 text-[11px] font-medium text-muted-foreground">动作</TableHead>
            <TableHead class="h-9 w-[72px] px-4 text-right text-[11px] font-medium text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          <template v-if="loading && !logs.length">
            <TableRow v-for="index in 6" :key="index" class="hover:bg-transparent">
              <TableCell class="px-4 py-2.5"><div class="h-3 w-16 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-36 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-56 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-5 w-10 animate-pulse rounded-md bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-20 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5" />
            </TableRow>
          </template>

          <TableRow v-else-if="error" class="hover:bg-transparent">
            <TableCell colspan="7" class="px-4 py-12 text-center">
              <p class="text-sm font-medium">日志加载失败</p>
              <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ error }}</p>
              <Button variant="outline" class="mt-4 h-9" @click="load()">
                <RefreshCw class="size-4" />
                重试
              </Button>
            </TableCell>
          </TableRow>

          <TableRow v-else-if="!logs.length" class="hover:bg-transparent">
            <TableCell colspan="7" class="px-4 py-14 text-center">
              <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
                <ScrollText class="size-4" />
              </span>
              <p class="mt-4 text-sm font-medium">{{ query || methodFilter !== 'all' || kindFilter !== 'all' ? '没有匹配的日志' : '还没有操作日志' }}</p>
              <p class="mt-1 text-sm text-muted-foreground">
                {{ query || methodFilter !== 'all' || kindFilter !== 'all' ? '调整筛选条件试试。' : '用户访问接口后会自动记录在这里。' }}
              </p>
            </TableCell>
          </TableRow>

          <template v-else>
            <TableRow v-for="log in logs" :key="log.id">
              <TableCell class="px-4 py-2.5 text-xs text-muted-foreground">
                <span :title="formatAdminTime(log.created_at)">{{ formatMessageTime(log.created_at) }}</span>
              </TableCell>
              <TableCell class="max-w-[190px] truncate px-4 py-2.5 text-xs">
                {{ log.actor_email || '匿名' }}
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <div class="flex min-w-0 items-center gap-2.5">
                  <Badge variant="outline" class="shrink-0 font-mono text-[10px]">
                    {{ log.method || (log.action ? 'ADMIN' : '—') }}
                  </Badge>
                  <span class="truncate text-xs" :title="log.path || log.route || ''">
                    {{ log.route || log.path || '—' }}
                  </span>
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <span class="inline-flex h-6 items-center rounded-md border px-1.5 font-mono text-[11px]" :class="httpStatusTone(log.status_code)">
                  {{ log.status_code ?? '—' }}
                </span>
              </TableCell>
              <TableCell class="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                {{ log.duration_ms != null ? `${log.duration_ms}ms` : '—' }}
              </TableCell>
              <TableCell class="max-w-[160px] px-4 py-2.5">
                <Badge variant="outline" class="max-w-full gap-1 font-normal">
                  <component :is="auditActionIcon(log)" class="size-3 text-muted-foreground" />
                  <span class="truncate">{{ operationLabel(log) }}</span>
                </Badge>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-right">
                <Button
                  variant="ghost"
                  class="h-8 gap-1 px-2 text-xs text-muted-foreground"
                  aria-label="查看日志详情"
                  @click="openDetail(log)"
                >
                  <Eye class="size-3.5" />
                  <span class="hidden sm:inline">详情</span>
                </Button>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>

      <template #footer>
        <p class="hidden text-xs text-muted-foreground sm:block">请求参数与返回结果已脱敏并限制长度</p>
        <div class="ml-auto flex flex-wrap items-center gap-4">
          <p class="text-xs tabular-nums text-muted-foreground">共 {{ total }} 条记录 · {{ rangeLabel }}</p>
          <AdminPager :offset="offset" :limit="limit" :total="total" @page="page" />
        </div>
      </template>
    </TableFrame>

    <Dialog v-model:open="detailOpen">
      <DialogContent class="console-surface flex h-[min(88vh,52rem)] w-[calc(100vw-2rem)] max-w-[980px] flex-col gap-0 overflow-hidden p-0 sm:max-w-[980px]">
        <DialogHeader class="shrink-0 border-b border-border/70 px-6 py-4 pr-14">
          <DialogTitle>{{ activeTitle }}</DialogTitle>
          <DialogDescription>
            请求与返回中的密码、token、API key 等敏感字段已脱敏。
          </DialogDescription>
        </DialogHeader>

        <div v-if="activeLog" class="flex min-h-0 flex-1 flex-col gap-4 px-6 py-5">
          <dl class="grid shrink-0 grid-cols-[80px_1fr] gap-x-3 gap-y-2 text-[13px]">
            <dt class="text-muted-foreground">时间</dt>
            <dd class="tabular-nums">{{ formatAdminTime(activeLog.created_at) }}</dd>
            <dt class="text-muted-foreground">用户</dt>
            <dd class="min-w-0 truncate">{{ activeLog.actor_email || '匿名' }}</dd>
            <dt class="text-muted-foreground">请求</dt>
            <dd class="min-w-0 break-all font-mono text-xs">
              {{ activeLog.method || '—' }} {{ activeLog.path || activeLog.route || '—' }}
            </dd>
            <dt class="text-muted-foreground">状态</dt>
            <dd class="font-mono">{{ activeLog.status_code ?? '—' }} · {{ activeLog.duration_ms ?? 0 }}ms</dd>
            <dt class="text-muted-foreground">request id</dt>
            <dd class="min-w-0 break-all font-mono text-[11px] text-muted-foreground/80">{{ activeLog.request_id || '—' }}</dd>
            <dt class="text-muted-foreground">客户端</dt>
            <dd class="min-w-0 truncate">{{ activeLog.client_ip || '—' }}<span v-if="activeLog.user_agent" class="text-muted-foreground/70"> · {{ activeLog.user_agent }}</span></dd>
          </dl>

          <Tabs v-model="detailTab" class="flex min-h-0 flex-1 flex-col gap-2">
            <div class="flex shrink-0 items-center gap-2">
              <TabsList class="h-8">
                <TabsTrigger value="request" class="px-3 text-xs">请求参数</TabsTrigger>
                <TabsTrigger value="response" class="px-3 text-xs">返回结果</TabsTrigger>
                <TabsTrigger v-if="activeLog.action" value="admin" class="px-3 text-xs">管理操作</TabsTrigger>
              </TabsList>
              <div class="ml-auto flex items-center gap-1.5">
                <Badge v-if="activeTruncated" variant="outline" class="text-amber-700 dark:text-amber-400">已截断</Badge>
                <ToolCodeCopy :code="activeCode" />
              </div>
            </div>

            <TabsContent value="request" class="flex min-h-0">
              <CodeBlock :code="requestJson" language="json" wrap :class="JSON_VIEW_CLASS" />
            </TabsContent>
            <TabsContent value="response" class="flex min-h-0">
              <CodeBlock :code="responseJson" language="json" wrap :class="JSON_VIEW_CLASS" />
            </TabsContent>
            <TabsContent v-if="activeLog.action" value="admin" class="flex min-h-0">
              <CodeBlock :code="adminJson" language="json" wrap :class="JSON_VIEW_CLASS" />
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
