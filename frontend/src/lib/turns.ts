import type { SessionRun, TokenUsage } from '@/types/api'

export interface TurnGroup {
  id: string
  run: SessionRun
  leaf: SessionRun
  runs: SessionRun[]
}

function sumUsage(runs: SessionRun[]): TokenUsage {
  return runs.reduce<TokenUsage>(
    (total, run) => ({
      requests: total.requests + run.usage.requests,
      input_tokens: total.input_tokens + run.usage.input_tokens,
      output_tokens: total.output_tokens + run.usage.output_tokens,
      cache_read_tokens: total.cache_read_tokens + run.usage.cache_read_tokens,
      cache_write_tokens: total.cache_write_tokens + run.usage.cache_write_tokens,
      total_tokens: total.total_tokens + run.usage.total_tokens,
    }),
    {
      requests: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      total_tokens: 0,
    },
  )
}

export function groupTurnRuns(runs: SessionRun[]): TurnGroup[] {
  const groups: TurnGroup[] = []
  const groupByRun = new Map<string, TurnGroup>()

  for (const run of runs) {
    const parentGroup = run.kind === 'resume' && run.parent_run_id
      ? groupByRun.get(run.parent_run_id)
      : undefined
    if (parentGroup) {
      parentGroup.runs.push(run)
      parentGroup.leaf = run
      groupByRun.set(run.id, parentGroup)
      continue
    }
    const group: TurnGroup = { id: run.id, run, leaf: run, runs: [run] }
    groups.push(group)
    groupByRun.set(run.id, group)
  }
  return groups
}

export function mergeTurnRuns(runs: SessionRun[]): SessionRun | null {
  const first = runs[0]
  const last = runs[runs.length - 1]
  if (!first || !last) return null
  return {
    ...first,
    seq: first.seq,
    content: runs.flatMap(run => run.content),
    status: last.status,
    usage: sumUsage(runs),
    branch: first.branch,
    created_at: first.created_at,
    updated_at: last.updated_at,
    preview: last.preview,
  }
}
