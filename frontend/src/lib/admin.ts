import type { Component } from 'vue'
import { Boxes, MessagesSquare, ScrollText, SlidersHorizontal, UsersRound } from '@lucide/vue'

import { parseServerDate } from '@/lib/format'
import type { AdminOperationLog } from '@/types/api'

export const AUDIT_ACTION_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: '全部动作' },
  { value: 'config.update', label: '更新配置' },
  { value: 'model.create', label: '新增模型' },
  { value: 'model.update', label: '更新模型' },
  { value: 'model.delete', label: '删除模型' },
  { value: 'user.update', label: '更新用户' },
  { value: 'user.password_reset', label: '重置密码' },
  { value: 'session.update', label: '更新会话' },
]

const AUDIT_ACTION_LABELS: Record<string, string> = Object.fromEntries(
  AUDIT_ACTION_OPTIONS.filter(item => item.value !== 'all').map(item => [item.value, item.label]),
)

export const AUDIT_TARGET_LABELS: Record<string, string> = {
  config: '配置',
  model: '模型',
  user: '用户',
  session: '会话',
}

const TARGET_ICONS: Record<string, Component> = {
  config: SlidersHorizontal,
  model: Boxes,
  user: UsersRound,
  session: MessagesSquare,
}

export function auditActionLabel(action: string | null): string {
  if (!action) return '请求'
  return AUDIT_ACTION_LABELS[action] ?? action
}

export function auditActionIcon(log: Pick<AdminOperationLog, 'target_type'>): Component {
  return (log.target_type && TARGET_ICONS[log.target_type]) || ScrollText
}

export function formatAdminTime(iso: string | null): string {
  if (!iso) return '—'
  const date = parseServerDate(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function formatAdminDate(iso: string | null): string {
  if (!iso) return '—'
  const date = parseServerDate(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}
