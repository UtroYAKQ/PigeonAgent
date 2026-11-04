export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** index
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`
}

export function formatTokens(value: number): string {
  if (!Number.isFinite(value)) return '0'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}k`
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function parseServerDate(value: string | Date): Date {
  if (value instanceof Date) return value
  const text = value.trim()
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`
  return new Date(normalized)
}

export function formatDuration(startIso: string, endIso?: string | null): string {
  const start = parseServerDate(startIso).getTime()
  const end = endIso ? parseServerDate(endIso).getTime() : Date.now()
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 1) return '不到 1 秒'
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

export function formatRelativeTime(iso: string): string {
  const date = parseServerDate(iso)
  const diff = Date.now() - date.getTime()
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour

  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

export function truncate(value: string, max = 80): string {
  const text = value.replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

export function fileTitleFromContent(input: string, fallback = '新对话'): string {
  const cleaned = input
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/<resource[^>]*\/>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!cleaned) return fallback

  const clause = cleaned.match(/^(.{4,28}?)[，,。！？；;!?]/)
  if (clause?.[1]) return clause[1].trim()

  const words = cleaned.split(' ')
  if (words.length > 1 && /^[\x00-\x7F]/.test(cleaned)) {
    let title = ''
    for (const word of words) {
      const next = title ? `${title} ${word}` : word
      if (next.length > 30) break
      title = next
    }
    if (title) return truncate(title, 30)
  }

  return truncate(cleaned, 28)
}

export function formatMessageTime(iso: string): string {
  const date = parseServerDate(iso)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfYesterday = startOfToday - 86_400_000
  const stamp = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
  if (date.getTime() >= startOfToday) return `今天 ${stamp}`
  if (date.getTime() >= startOfYesterday) return `昨天 ${stamp}`
  const day = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
  return `${day} ${stamp}`
}

/** 绝对日期时间：给「到期时间」这类未来时刻用。
 * formatMessageTime 会把任何晚于今天零点的日期都念成"今天"，不能拿来显示期限。 */
export function formatDateTime(iso: string): string {
  const date = parseServerDate(iso)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function parseJsonLike(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return ''
  if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
    try {
      return JSON.parse(text)
    } catch {
      return value
    }
  }
  return value
}

export function stringifyValue(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? '')
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/**
 * 积分显示：最多 4 位小数、去尾零（0.0017、99.99、100）。
 * 计费按 token 线性折算后常远小于 1，固定两位会变成一堆 0.00。
 */
export function formatCredits(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '0'
  return Number(value.toFixed(4)).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
