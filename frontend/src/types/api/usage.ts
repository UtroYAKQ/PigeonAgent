/* usage 领域类型。 */



export interface UsageTotals {
  today_tokens: number
  today_credits: number
  today_cache_read_tokens: number
  month_tokens: number
  month_credits: number
  month_cache_read_tokens: number
  month_runs: number
  runs_total: number
  range_input_tokens: number
  range_output_tokens: number
  range_cache_read_tokens: number
  range_credits: number
}

export interface UsageDaily {
  date: string
  tokens: number
  credits: number
  runs: number
  cache_read_tokens: number
}

export interface UsageModelStat {
  model_name: string | null
  runs: number
  tokens: number
  credits: number
  cache_read_tokens: number
}

export interface UsageRecent {
  created_at: string
  model_name: string | null
  status: string
  total_tokens: number
  cache_read_tokens: number
  credits_charged: number
  images_generated: number
}

export interface UsageOverview {
  balance: number
  billing_enabled: boolean
  totals: UsageTotals
  daily: UsageDaily[]
  by_model: UsageModelStat[]
  recent: UsageRecent[]
}
