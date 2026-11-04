<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity,
  CircleAlert,
  MessagesSquare,
  RefreshCw,
  ShieldCheck,
  UsersRound,
} from '@lucide/vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { adminApi } from '@/api/admin'
import { auditActionIcon, auditActionLabel, AUDIT_TARGET_LABELS, formatAdminTime } from '@/lib/admin'
import { formatMessageTime, formatTokens } from '@/lib/format'
import { errorMessage } from '@/lib/http'
import type { AdminOperationLog, AdminStats } from '@/types/api'

interface StatCard {
  label: string
  value: number
  note: string
  icon: Component
  tone?: 'destructive'
}

const router = useRouter()
const stats = ref<AdminStats | null>(null)
const recentLogs = ref<AdminOperationLog[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const failureRate = computed(() => {
  if (!stats.value?.runs_total) return 0
  return (stats.value.runs_failed / stats.value.runs_total) * 100
})

const activeUserRate = computed(() => {
  if (!stats.value?.users_total) return 0
  return (stats.value.users_active / stats.value.users_total) * 100
})

const activeSessionRate = computed(() => {
  if (!stats.value?.sessions_total) return 0
  return (stats.value.sessions_active / stats.value.sessions_total) * 100
})

const statCards = computed<StatCard[]>(() => {
  const value = stats.value
  if (!value) return []
  return [
    { label: '用户总数', value: value.users_total, note: '全部注册账号', icon: UsersRound },
    { label: '启用账号', value: value.users_active, note: `${Math.round(activeUserRate.value)}% 可登录`, icon: Activity },
    { label: '管理员', value: value.users_admin, note: '拥有管理权限', icon: ShieldCheck },
    { label: '会话总数', value: value.sessions_total, note: '全部对话', icon: MessagesSquare },
    { label: '活跃会话', value: value.sessions_active, note: `${Math.round(activeSessionRate.value)}% 未归档`, icon: MessagesSquare },
    { label: '归档会话', value: value.sessions_archived, note: '保留可恢复', icon: MessagesSquare },
    { label: '运行总数', value: value.runs_total, note: '累计运行轮次', icon: Activity },
    {
      label: '失败运行',
      value: value.runs_failed,
      note: value.runs_total
        ? value.runs_failed ? `${failureRate.value.toFixed(1)}% 失败率` : '运行全部正常'
        : '暂无运行记录',
      icon: CircleAlert,
      tone: 'destructive',
    },
  ]
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [statsData, logsData] = await Promise.all([
      adminApi.stats(),
      adminApi.logs({ limit: 7 }),
    ])
    stats.value = statsData
    recentLogs.value = logsData.items
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function goLogs(): void {
  void router.push({ name: 'admin', params: { section: 'logs' } })
}
</script>

<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between gap-3">
      <p class="text-sm font-medium">核心指标</p>
      <Button
        variant="outline"
        class="h-8"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <div v-if="loading && !stats" class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div v-for="index in 8" :key="index" class="h-[108px] animate-pulse rounded-xl border border-border bg-card" />
    </div>

    <div v-else-if="error" class="rounded-xl border border-border bg-card px-4 py-16 text-center">
      <p class="text-sm font-medium">统计加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ error }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <template v-else-if="stats">
      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div v-for="card in statCards" :key="card.label" class="rounded-xl border border-border bg-card p-4">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-medium">{{ card.label }}</span>
            <component :is="card.icon" class="size-4 text-muted-foreground" :stroke-width="1.8" />
          </div>
          <p
            class="mt-2.5 text-2xl font-bold leading-none tabular-nums"
            :class="card.tone === 'destructive' && card.value > 0 ? 'text-destructive' : ''"
          >
            {{ formatTokens(card.value) }}
          </p>
          <p class="mt-1.5 text-[11px] text-muted-foreground">{{ card.note }}</p>
        </div>
      </div>

      <div class="grid gap-3 xl:grid-cols-[minmax(0,1.65fr)_minmax(280px,1fr)]">
        <section class="overflow-hidden rounded-xl border border-border bg-card">
          <div class="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <p class="text-sm font-semibold">最近操作</p>
            <Button variant="ghost" class="h-8 text-muted-foreground" @click="goLogs">
              查看全部
            </Button>
          </div>
          <Table class="min-w-[540px] text-[13px]">
            <TableHeader>
              <TableRow>
                <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">时间</TableHead>
                <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">用户</TableHead>
                <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">动作</TableHead>
                <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">对象</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-if="!recentLogs.length" class="hover:bg-transparent">
                <TableCell colspan="4" class="px-4 py-10 text-center text-sm text-muted-foreground">
                  还没有操作记录
                </TableCell>
              </TableRow>
              <TableRow v-for="log in recentLogs" :key="log.id">
                <TableCell class="px-4 py-2.5 text-xs text-muted-foreground">
                  <span :title="formatAdminTime(log.created_at)">{{ formatMessageTime(log.created_at) }}</span>
                </TableCell>
                <TableCell class="max-w-[180px] truncate px-4 py-2.5 text-xs">
                  {{ log.actor_email || '系统' }}
                </TableCell>
                <TableCell class="px-4 py-2.5">
                  <Badge variant="outline" class="gap-1 font-normal">
                    <component :is="auditActionIcon(log)" class="size-3 text-muted-foreground" />
                    {{ log.action ? auditActionLabel(log.action) : `${log.method || 'HTTP'} ${log.route || log.path || ''}` }}
                  </Badge>
                </TableCell>
                <TableCell class="max-w-[180px] truncate px-4 py-2.5 text-xs text-muted-foreground">
                  <template v-if="log.action">
                    {{ (log.target_type && AUDIT_TARGET_LABELS[log.target_type]) || log.target_type || '操作' }}<span v-if="log.target_id"> · {{ log.target_id }}</span>
                  </template>
                  <template v-else>
                    {{ log.kind === 'request' ? '请求' : '操作' }}
                  </template>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>

        <div class="grid content-start gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <section class="rounded-xl border border-border bg-card p-4">
            <div class="flex items-center justify-between gap-2">
              <p class="text-sm font-medium">运行健康</p>
              <span class="text-xs tabular-nums text-muted-foreground">{{ failureRate.toFixed(1) }}% 失败</span>
            </div>
            <div class="mt-3 flex h-2 overflow-hidden rounded-full bg-muted">
              <div class="h-full bg-primary" :style="{ width: `${100 - failureRate}%` }" />
              <div class="h-full bg-destructive" :style="{ width: `${failureRate}%` }" />
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3">
              <div>
                <p class="text-xs text-muted-foreground">成功运行</p>
                <p class="mt-1 text-sm font-medium tabular-nums">
                  {{ formatTokens(stats.runs_total - stats.runs_failed) }}
                </p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">失败运行</p>
                <p
                  class="mt-1 text-sm font-medium tabular-nums"
                  :class="stats.runs_failed ? 'text-destructive' : ''"
                >
                  {{ formatTokens(stats.runs_failed) }}
                </p>
              </div>
            </div>
          </section>

          <section class="rounded-xl border border-border bg-card p-4">
            <div class="flex items-center justify-between gap-2">
              <p class="text-sm font-medium">会话分布</p>
              <span class="text-xs tabular-nums text-muted-foreground">{{ Math.round(activeSessionRate) }}% 活跃</span>
            </div>
            <div class="mt-3 flex h-2 overflow-hidden rounded-full bg-muted">
              <div class="h-full bg-primary" :style="{ width: `${activeSessionRate}%` }" />
              <div class="h-full bg-muted-foreground/30" :style="{ width: `${100 - activeSessionRate}%` }" />
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3">
              <div>
                <p class="text-xs text-muted-foreground">活跃</p>
                <p class="mt-1 text-sm font-medium tabular-nums">{{ formatTokens(stats.sessions_active) }}</p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">归档</p>
                <p class="mt-1 text-sm font-medium tabular-nums">{{ formatTokens(stats.sessions_archived) }}</p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
