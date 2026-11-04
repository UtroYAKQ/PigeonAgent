import type { AgUiEvent } from '@/types/api'
import { accessToken } from './authStorage'
import { refreshAccessToken } from './http'

export class StreamGoneError extends Error {
  constructor(message = '运行已结束') {
    super(message)
    this.name = 'StreamGoneError'
  }
}

export interface StreamOptions {
  url: string
  signal: AbortSignal
  onEvent: (event: AgUiEvent) => void
  onOpen?: () => void
  onSequence?: (sequence: number) => void
}

/** 解析 SSE 数据帧：没有 type 字段的帧不是事件，静默跳过。 */
export function parseAgUiEvent(raw: unknown): AgUiEvent | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  if (typeof record.type !== 'string' || !record.type) return null
  return raw as AgUiEvent
}

interface ParsedFrame {
  id?: number
  data: string
}

function parseFrame(raw: string): ParsedFrame | null {
  let id: number | undefined
  const data: string[] = []

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'id') {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) id = parsed
    } else if (field === 'data') {
      data.push(value)
    }
  }

  if (data.length === 0) return null
  return { id, data: data.join('\n') }
}

/** 事件流的请求形状；首连和 401 重连只差在带哪个 token。 */
function streamRequestInit(signal: AbortSignal, token: string | null): RequestInit {
  return {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
  }
}

async function openResponse(options: StreamOptions): Promise<Response> {
  const response = await fetch(options.url, streamRequestInit(options.signal, accessToken()))
  if (response.status !== 401) return response
  // 只重连一次：refreshAccessToken 失败会抛出（并在 http 里广播登录过期），这里不吞
  const token = await refreshAccessToken()
  return fetch(options.url, streamRequestInit(options.signal, token))
}

export async function streamRun(options: StreamOptions): Promise<void> {
  const response = await openResponse(options)

  if (response.status === 410) {
    throw new StreamGoneError()
  }
  if (!response.ok) {
    let message = `事件流连接失败（${response.status}）`
    try {
      const payload = await response.json() as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // 网关或旧后端会直接回 HTML 错误页：没 JSON 就没 detail，状态码文案照样抛得出去
    }
    throw new Error(message)
  }
  if (!response.body) {
    throw new Error('事件流没有响应体')
  }

  options.onOpen?.()

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const emitFrame = (raw: string): void => {
    const frame = parseFrame(raw)
    if (!frame) return
    if (frame.id != null) options.onSequence?.(frame.id)
    try {
      const parsed = parseAgUiEvent(JSON.parse(frame.data))
      if (parsed) options.onEvent(parsed)
    } catch (error) {
      console.warn('无法解析 SSE 事件', error, frame.data)
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.search(/\r?\n\r?\n/)
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary)
        const separatorLength = buffer.slice(boundary).startsWith('\r\n\r\n') ? 4 : 2
        buffer = buffer.slice(boundary + separatorLength)
        emitFrame(raw)
        boundary = buffer.search(/\r?\n\r?\n/)
      }
    }
    // 连接结束时 TextDecoder 可能还压着半个多字节字符，残帧也要处理
    buffer += decoder.decode()
    if (buffer.trim()) emitFrame(buffer)
  } finally {
    reader.releaseLock()
  }
}
