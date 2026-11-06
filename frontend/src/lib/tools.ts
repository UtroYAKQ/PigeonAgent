import type { BundledLanguage, SpecialLanguage } from 'shiki'

import type { LiveToolState, RunItem, ToolOutcome, ToolResultItem } from '@/types/api'
import { parseJsonLike, truncate } from './format'

export type ToolState = 'running' | 'waiting' | 'success' | 'failed' | 'interrupted'

export interface ToolStep {
  id: string
  name: string
  args: unknown
  result: unknown
  outcome: ToolOutcome | null
  state: ToolState
  label: string
  detail: string | null
  icon: string
}

const TOOL_ICONS: Record<string, string> = {
  get_current_time: 'clock',
  run_command: 'terminal',
  load_files: 'files',
  list_files: 'folder',
  read_file: 'file',
  write_file: 'edit',
  publish_file: 'upload',
  generate_image: 'image',
  read_image: 'image',
  web_search: 'search',
  search: 'search',
  file_search: 'search',
  browse: 'globe',
  fetch_url: 'globe',
}

function toolIcon(name: string): string {
  if (TOOL_ICONS[name]) return TOOL_ICONS[name]
  if (name.startsWith('fetch_')) return 'globe'
  if (name.includes('search')) return 'search'
  if (name.includes('file')) return 'file'
  return 'wrench'
}

/** 工具的人类可读名；兜底文案用它，没登记就退化成原名去下划线。 */
const TOOL_NAMES: Record<string, string> = {
  write_file: '写入文件',
  read_file: '读取文件',
  ui_open_html_preview: '准备页面预览',
  generate_image: '生成图片',
  read_image: '读取图片',
}

/**
 * 一个工具一行状态文案。running/done 必填，failed/paused 只在这个工具真会被拒绝或打断时才写；
 * 缺了就退到 toolLabel 末尾按人类可读名生成。新增工具通常只要在这里加一行。
 */
interface ToolCopy {
  running: string
  done: string
  failed?: string
  paused?: string
}

const TOOL_COPY: Record<string, ToolCopy> = {
  run_command: {
    running: '正在运行代码',
    done: '代码运行完成',
    failed: '代码运行失败',
    paused: '代码运行已暂停',
  },
  generate_image: { running: '正在生成图片', done: '图片已生成', paused: '图片生成已停止' },
  read_image: { running: '正在读取图片', done: '图片已读取', failed: '图片读取失败' },
  web_search: { running: '正在搜索网页', done: '搜索完成', failed: '搜索失败', paused: '搜索已暂停' },
  fetch_url: { running: '正在读取网页', done: '网页已读取', failed: '网页读取失败', paused: '网页读取已暂停' },
  ui_open_html_preview: { running: '正在生成预览', done: '预览已生成' },
  get_current_time: { running: '正在查询当前时间', done: '已获取当前时间' },
  load_files: { running: '正在加载文件', done: '已加载文件' },
  list_files: { running: '正在浏览工作区', done: '已浏览工作区' },
  read_file: { running: '正在读取文件', done: '已读取文件' },
  write_file: { running: '正在写入文件', done: '已写入文件' },
  publish_file: { running: '正在发布文件', done: '已发布文件' },
}

export function toolLabel(name: string, state: ToolState): string {
  const human = TOOL_NAMES[name] ?? name.replace(/_/g, ' ').trim()
  const copy = TOOL_COPY[name]
  if (state === 'interrupted') return copy?.paused ?? `已暂停 · ${human}`
  if (state === 'failed') return copy?.failed ?? `${human}失败`

  const running = state === 'running' || state === 'waiting'
  if (copy) return running ? copy.running : copy.done
  // 后端工具名多到不可能逐个登记时，先按名字里的模式给个通用说法
  if (name.includes('search')) return running ? '正在搜索' : '搜索完成'
  if (name.startsWith('fetch_')) return running ? '正在获取外部数据' : '已获取外部数据'
  return running ? `正在调用 ${human}` : `已调用 ${human}`
}

function toolDetail(name: string, args: unknown): string | null {
  // 文件工具的参数可能是半截 JSON（流式中断），优先取文件名，别再显示整段原始 JSON
  if (name === 'read_file' || name === 'write_file' || name === 'publish_file' || name === 'read_image') {
    const value = parseJsonLike(args)
    if (value && typeof value === 'object') {
      const data = value as Record<string, unknown>
      if (typeof data.name === 'string') return data.name
      if (typeof data.path === 'string') return data.path
      if (typeof data.source === 'string') return data.source
    }
    if (typeof value === 'string') {
      const match = /"(?:name|path)"\s*:\s*"((?:\\.|[^"\\])*)"/.exec(value)
      if (match?.[1]) return match[1]
    }
    return null
  }

  const value = parseJsonLike(args)
  if (!value || typeof value !== 'object') {
    return typeof value === 'string' && value.trim() ? truncate(value, 60) : null
  }
  const data = value as Record<string, unknown>
  if (name === 'run_command') {
    return typeof data.command === 'string' ? truncate(data.command, 90) : null
  }
  if (name === 'load_files') {
    return Array.isArray(data.storage_keys) ? `加载 ${data.storage_keys.length} 个文件` : null
  }
  if (name === 'list_files') {
    return typeof data.subdir === 'string' ? data.subdir : null
  }
  if (name === 'get_current_time') {
    return typeof data.timezone === 'string' ? data.timezone : null
  }
  if (name === 'web_search') {
    return typeof data.query === 'string' ? truncate(data.query, 60) : null
  }
  if (name === 'fetch_url') {
    return typeof data.url === 'string' ? truncate(data.url, 60) : null
  }
  const firstString = Object.values(data).find(item => typeof item === 'string')
  return typeof firstString === 'string' ? truncate(firstString, 60) : null
}

export function buildToolSteps(items: RunItem[], externalResults?: Map<string, ToolResultItem>): ToolStep[] {
  const calls: { id: string; name: string; args: unknown }[] = []
  const results = new Map<string, { content: unknown; outcome: ToolOutcome }>()

  for (const item of items) {
    if (item.type === 'tool_call') {
      calls.push({ id: item.tool_call_id, name: item.tool_name, args: item.args })
    }
    if (item.type === 'tool_result') {
      results.set(item.tool_call_id, { content: item.content, outcome: item.outcome })
    }
  }

  return calls.map((call) => {
    const local = results.get(call.id)
    const external = externalResults?.get(call.id)
    const result = local ?? (external ? { content: external.content, outcome: external.outcome } : null)
    let state: ToolState = result ? 'success' : 'running'
    if (result) {
      if (result.outcome === 'failed' || result.outcome === 'denied') state = 'failed'
      else if (result.outcome === 'interrupted') state = 'interrupted'
    }
    return {
      id: call.id,
      name: call.name,
      args: call.args,
      result: result?.content ?? null,
      outcome: result?.outcome ?? null,
      state,
      label: toolLabel(call.name, state),
      detail: toolDetail(call.name, call.args),
      icon: toolIcon(call.name),
    }
  })
}

export function liveToolStep(tool: LiveToolState): ToolStep {
  const args = parseJsonLike(tool.argsText)
  return {
    id: tool.toolCallId,
    name: tool.name,
    args,
    result: tool.resultText ? parseJsonLike(tool.resultText) : null,
    outcome: null,
    state: tool.state,
    label: toolLabel(tool.name, tool.state),
    detail: toolDetail(tool.name, args),
    icon: toolIcon(tool.name),
  }
}

export interface TerminalOutput {
  stdout: string
  stderr: string
  exitCode: number | null
  command: string | null
}

export function commandFromStep(step: ToolStep): string | null {
  const parsed = parseJsonLike(step.args)
  if (parsed && typeof parsed === 'object' && typeof (parsed as Record<string, unknown>).command === 'string') {
    return (parsed as Record<string, string>).command
  }
  return null
}

export function terminalFromStep(step: ToolStep): TerminalOutput | null {
  const parsed = parseJsonLike(step.result)
  if (!parsed || typeof parsed !== 'object') return null
  const data = parsed as Record<string, unknown>
  if (typeof data.stdout !== 'string' && typeof data.stderr !== 'string') return null
  return {
    stdout: typeof data.stdout === 'string' ? data.stdout : '',
    stderr: typeof data.stderr === 'string' ? data.stderr : '',
    exitCode: typeof data.exit_code === 'number' ? data.exit_code : null,
    command: commandFromStep(step),
  }
}

export interface MediaPayload {
  kind: 'image' | 'video' | 'resource'
  mediaType: string
  data?: string
  url?: string
  name?: string
  fileId?: string
  size?: number
}

/** media_type 到渲染种类的唯一判断；turnModel 的产物也用同一个口径 */
export function mediaKind(mediaType: string): 'image' | 'video' | 'file' {
  if (mediaType.startsWith('image/')) return 'image'
  if (mediaType.startsWith('video/')) return 'video'
  return 'file'
}

export function findMedia(value: unknown, bucket: MediaPayload[] = [], seen = new Set<string>()): MediaPayload[] {
  if (!value) return bucket
  if (Array.isArray(value)) {
    for (const item of value) findMedia(item, bucket, seen)
    return bucket
  }
  if (typeof value !== 'object') return bucket

  const data = value as Record<string, unknown>
  const mediaType = typeof data.media_type === 'string' ? data.media_type : null

  if (data.media === 'binary' && typeof data.data === 'string' && mediaType) {
    const key = `binary:${mediaType}:${data.data.slice(0, 48)}`
    if (!seen.has(key)) {
      seen.add(key)
      const kind = mediaKind(mediaType)
      if (kind === 'image' || kind === 'video') {
        bucket.push({ kind, mediaType, data: data.data })
      }
    }
    return bucket
  }

  if (typeof data.media === 'string' && data.media.endsWith('-url') && typeof data.url === 'string' && mediaType) {
    const key = `url:${data.url}`
    if (!seen.has(key)) {
      seen.add(key)
      const kind = mediaKind(mediaType)
      if (kind === 'image' || kind === 'video') {
        bucket.push({ kind, mediaType, url: data.url })
      }
    }
    return bucket
  }

  const fileId = typeof data.file_id === 'string' ? data.file_id : null
  if (fileId && typeof data.name === 'string' && mediaType && fileId.length >= 32) {
    const key = `resource:${fileId}`
    if (!seen.has(key)) {
      seen.add(key)
      bucket.push({
        kind: 'resource',
        mediaType,
        name: data.name,
        fileId,
        size: typeof data.size === 'number' ? data.size : undefined,
      })
    }
    return bucket
  }

  for (const item of Object.values(data)) {
    findMedia(item, bucket, seen)
  }
  return bucket
}

/**
 * write_file 的语言判定：文件名在 args 里排在内容后面，
 * 所以写入过程中要先按内容开头猜，否则整段流式期都是纯文本。
 */
const FILE_LANGUAGES: Record<string, BundledLanguage> = {
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  vue: 'vue',
  json: 'json',
  md: 'markdown',
  markdown: 'markdown',
  py: 'python',
  sh: 'bash',
  bash: 'bash',
  yml: 'yaml',
  yaml: 'yaml',
  toml: 'toml',
  sql: 'sql',
  go: 'go',
  rs: 'rust',
  java: 'java',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  php: 'php',
  rb: 'ruby',
  swift: 'swift',
  kt: 'kotlin',
  xml: 'xml',
  svg: 'xml',
}

const LANGUAGE_SNIFFERS: [RegExp, BundledLanguage][] = [
  [/^<!doctype\s+html|^<html[\s>]|^<(?:head|body|div|section|main|article|svg)[\s>]/i, 'html'],
  [/^[{[]/, 'json'],
  [/^<[\w:?-]+[\s/>]/, 'xml'],
  [/^(?:@|\/\*|:root|[.#][\w-]+\s*\{)/, 'css'],
  [/^(?:from\s+[\w.]+ import|def |async def |class \w+\s*[:(])/m, 'python'],
  [/^(?:import\s|export\s|const\s|let\s|var\s|function\s|class\s)/, 'typescript'],
  [/^package\s\w/, 'go'],
  [/^(?:#(?:\s|$)|[-*]\s|>\s)/, 'markdown'],
]

export function fileLanguage(
  name: string | null,
  content: string,
): BundledLanguage | SpecialLanguage {
  if (name?.includes('.')) {
    const extension = name.split('.').pop()?.toLowerCase() ?? ''
    return FILE_LANGUAGES[extension] ?? 'text'
  }
  const head = content.trimStart().slice(0, 160)
  if (!head) return 'text'
  for (const [pattern, language] of LANGUAGE_SNIFFERS) {
    if (pattern.test(head)) return language
  }
  return 'text'
}
