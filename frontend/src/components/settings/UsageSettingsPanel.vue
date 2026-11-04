<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, Coins, RefreshCw } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { usageApi } from '@/api/usage'
import { formatCredits, formatRelativeTime, formatTokens } from '@/lib/format'
import { errorMessage } from '@/lib/http'
import { useAuthStore } from '@/stores/auth'
import type { UsageOverview } from '@/types/api'

const auth = useAuthStore()
const overview = ref<UsageOverview | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    overview.value = await usageApi.overview()
    // 侧栏账户菜单的余额从这里保持新鲜
    if (auth.user) {
      auth.user = { ...auth.user, credits_balance: overview.value.balance }
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

onMounted(() => load())

// ------------------------------------------------------------------ 热力图
// 列=周、行=周一~周日，和 GitHub 贡献图同构；热度按当天 token 数分五档

interface HeatCell {
  date: string
  tokens: number
  credits: number
  runs: number
  cacheRead: number
  level: 0 | 1 | 2 | 3 | 4
  offset?: boolean
}

const LEVEL_CLASSES = [
  'bg-muted',
  'bg-emerald-500/25',
  'bg-emerald-500/45',
  'bg-emerald-500/70',
  'bg-emerald-600',
] as const

const heatCells = computed<HeatCell[]>(() => {
  const daily = overview.value?.daily ?? []
  if (!daily.length) return []
  const maxTokens = Math.max(...daily.map(day => day.tokens), 1)

  const first = new Date(`${daily[0]!.date}T00:00:00Z`)
  // getUTCDay: 0=周日；转成"周一=0"的偏移，第一列前面补空格
  const weekdayOffset = (first.getUTCDay() + 6) % 7

  const cells: HeatCell[] = []
  for (let i = 0; i < weekdayOffset; i += 1) {
    cells.push({ date: '', tokens: 0, credits: 0, runs: 0, cacheRead: 0, level: 0, offset: true })
  }
  for (const day of daily) {
    const ratio = day.tokens / maxTokens
    const level: HeatCell['level'] =
      day.tokens === 0 ? 0 : ratio > 0.75 ? 4 : ratio > 0.5 ? 3 : ratio > 0.25 ? 2 : 1
    cells.push({
      date: day.date,
      tokens: day.tokens,
      credits: day.credits,
      runs: day.runs,
      cacheRead: day.cache_read_tokens,
      level,
    })
  }
  // 末尾补齐到整周，格子矩阵才不会缺角
  while (cells.length % 7 !== 0) {
    cells.push({ date: '', tokens: 0, credits: 0, runs: 0, cacheRead: 0, level: 0, offset: true })
  }
  return cells
})

const peakTokens = computed(() => Math.max(...(overview.value?.daily ?? []).map(d => d.tokens), 0))
const rangeTokens = computed(() =>
  (overview.value?.daily ?? []).reduce((total, day) => total + day.tokens, 0),
)
const activeDays = computed(
  () => (overview.value?.daily ?? []).filter(day => day.runs > 0).length,
)
const rangeAverage = computed(() =>
  activeDays.value ? Math.round(rangeTokens.value / activeDays.value) : 0,
)

interface UsageSummaryRow {
  label: string
  value: string
  indent?: boolean
  strong?: boolean
}

const summaryRows = computed<UsageSummaryRow[]>(() => {
  const data = overview.value
  if (!data) return []
  const totals = data.totals
  const rows: UsageSummaryRow[] = [
    { label: '输入 tokens', value: formatTokens(totals.range_input_tokens) },
    { label: '其中缓存', value: formatTokens(totals.range_cache_read_tokens), indent: true },
    { label: '输出 tokens', value: formatTokens(totals.range_output_tokens) },
    { label: '总 tokens', value: formatTokens(rangeTokens.value), strong: true },
    { label: '对话轮数', value: `${totals.runs_total} 轮` },
    { label: '活跃天数', value: `${activeDays.value} 天` },
    { label: '活跃日均', value: `${formatTokens(rangeAverage.value)} tokens` },
    { label: '单日峰值', value: `${formatTokens(peakTokens.value)} tokens` },
  ]
  if (data.billing_enabled) {
    rows.push({ label: '积分消耗', value: `${formatCredits(totals.range_credits)} 积分` })
  }
  return rows
})

// 模型分布是近 13 周口径，占比分母也必须是同一窗口的总量，不能拿本月或今日凑
const byModelTotal = computed(() =>
  (overview.value?.by_model ?? []).reduce((total, stat) => total + stat.tokens, 0),
)

function cellTitle(cell: HeatCell): string {
  if (cell.offset) return ''
  const parts = [cell.date]
  parts.push(`${formatTokens(cell.tokens)} tokens`)
  if (cell.cacheRead) parts.push(`缓存命中 ${formatTokens(cell.cacheRead)}`)
  if (cell.runs) parts.push(`${cell.runs} 轮对话`)
  if (overview.value?.billing_enabled) parts.push(`${formatCredits(cell.credits)} 积分`)
  return parts.join(' · ')
}

const statusTone = (status: string): string =>
  status === 'completed'
    ? 'bg-primary'
    : status === 'failed'
      ? 'bg-destructive'
      : 'bg-muted-foreground/40'

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  interrupted: '待恢复',
  failed: '失败',
  cancelled: '已取消',
  running: '运行中',
  unknown: '未知',
}
</script>

<template>
  <div class="space-y-6">
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

    <template v-if="overview">
      <!-- 汇总卡片 -->
      <div class="grid gap-3 sm:grid-cols-3">
        <div class="rounded-xl border border-border/80 p-4">
          <p class="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Coins class="size-3.5" />
            积分余额
          </p>
          <p
            class="mt-1.5 font-mono text-[22px] font-medium tabular-nums leading-7"
            :class="overview.balance < 0 ? 'text-destructive' : ''"
          >
            {{ formatCredits(overview.balance) }}
          </p>
          <p class="mt-0.5 text-[11.5px] text-muted-foreground">
            {{ overview.balance < 0
              ? '已欠费，充值后会自动抵扣；欠费期间无法发起新对话。'
              : overview.billing_enabled ? '计费已开启，按 token 用量扣减' : '计费未开启，当前不扣分' }}
          </p>
        </div>
        <div class="rounded-xl border border-border/80 p-4">
          <p class="text-[12px] text-muted-foreground">今日用量</p>
          <p class="mt-1.5 font-mono text-[22px] font-medium tabular-nums leading-7">
            {{ formatTokens(overview.totals.today_tokens) }}
            <span class="text-[12px] font-normal text-muted-foreground">tokens</span>
          </p>
          <p v-if="overview.billing_enabled" class="mt-0.5 text-[11.5px] text-muted-foreground">
            {{ formatCredits(overview.totals.today_credits) }} 积分
          </p>
          <p v-if="overview.totals.today_cache_read_tokens" class="mt-0.5 text-[11.5px] text-muted-foreground">
            缓存命中 {{ formatTokens(overview.totals.today_cache_read_tokens) }}
          </p>
        </div>
        <div class="rounded-xl border border-border/80 p-4">
          <p class="text-[12px] text-muted-foreground">本月用量</p>
          <p class="mt-1.5 font-mono text-[22px] font-medium tabular-nums leading-7">
            {{ formatTokens(overview.totals.month_tokens) }}
            <span class="text-[12px] font-normal text-muted-foreground">tokens</span>
          </p>
          <p class="mt-0.5 text-[11.5px] text-muted-foreground">共 {{ overview.totals.month_runs }} 轮</p>
          <p v-if="overview.billing_enabled" class="mt-0.5 text-[11.5px] text-muted-foreground">
            {{ formatCredits(overview.totals.month_credits) }} 积分
          </p>
          <p v-if="overview.totals.month_cache_read_tokens" class="mt-0.5 text-[11.5px] text-muted-foreground">
            缓存命中 {{ formatTokens(overview.totals.month_cache_read_tokens) }}
          </p>
        </div>
      </div>

      <!-- 每日热力图 -->
      <ConsoleSection
        title="每日用量"
        :description="`过去 13 周，共 ${overview.totals.runs_total} 轮对话；每格一天，颜色越深说明当天消耗的 token 越多。`"
      >
        <div class="grid gap-6 lg:grid-cols-2 lg:gap-10">
          <div class="min-w-0 overflow-x-auto pb-1">
            <div class="mx-auto flex w-full max-w-[470px] flex-col gap-2.5 sm:gap-3">
              <div class="grid w-full auto-cols-fr grid-flow-col grid-rows-7 gap-1 sm:gap-1.5">
                <span
                  v-for="(cell, index) in heatCells"
                  :key="index"
                  class="aspect-square w-full rounded-[3px] sm:rounded-[5px]"
                  :class="cell.offset ? 'bg-transparent' : LEVEL_CLASSES[cell.level]"
                  :title="cellTitle(cell)"
                />
              </div>
              <div class="flex items-center gap-1.5 text-[11px] text-muted-foreground sm:gap-2 sm:text-[12px]">
                <span>少</span>
                <span
                  v-for="(cls, index) in LEVEL_CLASSES"
                  :key="index"
                  class="size-4 rounded-[3px] sm:size-5 sm:rounded-[4px]"
                  :class="cls"
                />
                <span>多</span>
              </div>
            </div>
          </div>

          <div class="min-w-0 border-t border-border/60 pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <div class="flex items-baseline justify-between gap-3">
              <p class="text-[12.5px] font-medium">近 13 周统计</p>
              <p class="text-[11px] text-muted-foreground">输入含缓存</p>
            </div>
            <table class="mt-2.5 w-full text-[12.5px]">
              <tbody class="divide-y divide-border/50">
                <tr v-for="row in summaryRows" :key="row.label">
                  <th
                    scope="row"
                    class="py-1.5 text-left font-normal text-muted-foreground"
                    :class="[row.indent ? 'pl-3' : '', row.strong ? 'font-medium text-foreground' : '']"
                  >
                    {{ row.label }}
                  </th>
                  <td
                    class="py-1.5 text-right font-mono tabular-nums"
                    :class="row.strong ? 'font-medium text-foreground' : ''"
                  >
                    {{ row.value }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </ConsoleSection>

      <!-- 模型分布 -->
      <ConsoleSection title="模型分布" description="近 13 周各模型的 token 消耗占比。">
        <div v-if="overview.by_model.length" class="space-y-3">
          <div v-for="stat in overview.by_model" :key="stat.model_name ?? 'unknown'">
            <div class="mb-1 flex items-baseline justify-between gap-3 text-[12.5px]">
              <span class="truncate font-medium">{{ stat.model_name || '未知模型' }}</span>
              <span class="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
                {{ formatTokens(stat.tokens) }} tokens
                <template v-if="stat.cache_read_tokens">
                  · 缓存命中 {{ formatTokens(stat.cache_read_tokens) }}
                </template>
                · {{ stat.runs }} 轮
                <template v-if="overview.billing_enabled && stat.credits > 0">
                  · {{ formatCredits(stat.credits) }} 积分
                </template>
              </span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full bg-primary/70"
                :style="{ width: `${stat.tokens && byModelTotal ? Math.max((stat.tokens / byModelTotal) * 100, 2) : 0}%` }"
              />
            </div>
          </div>
        </div>
        <p v-else class="text-sm text-muted-foreground">还没有对话记录。</p>
      </ConsoleSection>

      <!-- 最近对话 -->
      <ConsoleSection title="最近对话" description="最近几轮对话的用量与扣分。">
        <div v-if="overview.recent.length" class="divide-y divide-border/60">
          <div
            v-for="(item, index) in overview.recent"
            :key="index"
            class="flex items-center gap-3 py-2.5 text-[13px]"
          >
            <span class="size-2 shrink-0 rounded-full" :class="statusTone(item.status)" />
            <span class="min-w-0 flex-1 truncate">
              {{ item.model_name || '未知模型' }}
              <span class="ml-2 text-[11.5px] text-muted-foreground">
                {{ STATUS_LABELS[item.status] ?? item.status }}
              </span>
            </span>
            <span class="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
              {{ formatTokens(item.total_tokens) }} tokens
              <template v-if="item.cache_read_tokens">
                · 缓存命中 {{ formatTokens(item.cache_read_tokens) }}
              </template>
              <template v-if="overview.billing_enabled && item.credits_charged > 0">
                · -{{ formatCredits(item.credits_charged) }}
              </template>
              <template v-if="item.images_generated"> · {{ item.images_generated }} 图</template>
              · {{ formatRelativeTime(item.created_at) }}
            </span>
          </div>
        </div>
        <p v-else class="text-sm text-muted-foreground">还没有对话记录。</p>
      </ConsoleSection>
    </template>

    <div v-else-if="loading" class="space-y-4">
      <div class="grid gap-3 sm:grid-cols-3">
        <div v-for="index in 3" :key="index" class="h-[92px] animate-pulse rounded-xl bg-muted/60" />
      </div>
      <div class="h-[140px] animate-pulse rounded-xl bg-muted/60" />
    </div>

    <Button v-else variant="outline" class="h-9" @click="load()">
      <RefreshCw class="size-4" />
      重试
    </Button>

    <p class="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
      <Activity class="size-3.5" />
      余额与扣分如有疑问，请联系管理员在后台「用量与积分」里核对流水。
    </p>
  </div>
</template>
