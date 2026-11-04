import type { HighlighterCore, LanguageRegistration, ThemeInput } from 'shiki/core'
import { createHighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'
import { shallowRef } from 'vue'

export const HIGHLIGHT_THEMES = { light: 'min-light', dark: 'min-dark' } as const

type GrammarLoader = () => Promise<{ default: LanguageRegistration[] }>

const THEMES: ThemeInput[] = [
  () => import('shiki/themes/min-light.mjs'),
  () => import('shiki/themes/min-dark.mjs'),
]

// 只登记项目用得上的语法：走 shiki 主入口会把两百多种语言全部编成懒加载 chunk
const GRAMMARS = {
  bash: () => import('shiki/langs/bash.mjs'),
  c: () => import('shiki/langs/c.mjs'),
  cpp: () => import('shiki/langs/cpp.mjs'),
  csharp: () => import('shiki/langs/csharp.mjs'),
  css: () => import('shiki/langs/css.mjs'),
  diff: () => import('shiki/langs/diff.mjs'),
  dockerfile: () => import('shiki/langs/dockerfile.mjs'),
  go: () => import('shiki/langs/go.mjs'),
  html: () => import('shiki/langs/html.mjs'),
  java: () => import('shiki/langs/java.mjs'),
  javascript: () => import('shiki/langs/javascript.mjs'),
  json: () => import('shiki/langs/json.mjs'),
  jsonc: () => import('shiki/langs/jsonc.mjs'),
  jsx: () => import('shiki/langs/jsx.mjs'),
  kotlin: () => import('shiki/langs/kotlin.mjs'),
  markdown: () => import('shiki/langs/markdown.mjs'),
  mermaid: () => import('shiki/langs/mermaid.mjs'),
  php: () => import('shiki/langs/php.mjs'),
  python: () => import('shiki/langs/python.mjs'),
  ruby: () => import('shiki/langs/ruby.mjs'),
  rust: () => import('shiki/langs/rust.mjs'),
  scss: () => import('shiki/langs/scss.mjs'),
  sql: () => import('shiki/langs/sql.mjs'),
  swift: () => import('shiki/langs/swift.mjs'),
  toml: () => import('shiki/langs/toml.mjs'),
  tsx: () => import('shiki/langs/tsx.mjs'),
  typescript: () => import('shiki/langs/typescript.mjs'),
  vue: () => import('shiki/langs/vue.mjs'),
  xml: () => import('shiki/langs/xml.mjs'),
  yaml: () => import('shiki/langs/yaml.mjs'),
} satisfies Record<string, GrammarLoader>

type KnownLanguage = keyof typeof GRAMMARS

// 首屏最常见的语言随初始化一起加载，其余等代码块真正出现时再补
const EAGER_LANGUAGES: KnownLanguage[] = [
  'json',
  'javascript',
  'typescript',
  'tsx',
  'jsx',
  'vue',
  'html',
  'css',
  'python',
  'bash',
  'sql',
  'yaml',
  'markdown',
]

const ALIASES: Record<string, string> = {
  js: 'javascript',
  ts: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  yml: 'yaml',
  md: 'markdown',
  plaintext: 'text',
  txt: 'text',
}

let instance: HighlighterCore | null = null
let started: Promise<HighlighterCore | null> | null = null
const loaded = new Set<string>()
const failed = new Set<string>()
const pending = new Map<string, Promise<boolean>>()

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// 流式期已完成的代码块内容不变，重跑 Shiki 纯属浪费。
// 缓存按写入顺序淘汰，限制在 2MB 左右，长会话不会把内存撑起来。
const CACHE_LIMIT_BYTES = 2 * 1024 * 1024
const highlightCache = new Map<string, string>()
let cacheBytes = 0

function readCache(key: string): string | undefined {
  const hit = highlightCache.get(key)
  if (hit) {
    // 命中后重新插入，让热点内容留在缓存里
    highlightCache.delete(key)
    highlightCache.set(key, hit)
  }
  return hit
}

function writeCache(key: string, html: string): void {
  highlightCache.set(key, html)
  cacheBytes += key.length + html.length
  while (cacheBytes > CACHE_LIMIT_BYTES && highlightCache.size > 1) {
    const oldest = highlightCache.keys().next().value as string | undefined
    if (oldest === undefined) break
    const dropped = highlightCache.get(oldest)
    highlightCache.delete(oldest)
    cacheBytes -= oldest.length + (dropped?.length ?? 0)
  }
}

/** 高亮器或某个语言就绪时自增；代码块用它触发重新高亮。 */
export const highlightEpoch = shallowRef(0)

export function normalizeLanguage(language: string): string {
  const value = language.trim().toLowerCase()
  return ALIASES[value] ?? (value || 'text')
}

function grammarOf(language: string): GrammarLoader | undefined {
  return Object.hasOwn(GRAMMARS, language)
    ? GRAMMARS[language as KnownLanguage]
    : undefined
}

export function ensureHighlighter(): Promise<HighlighterCore | null> {
  if (!started) {
    started = createHighlighterCore({
      themes: THEMES,
      langs: EAGER_LANGUAGES.map(name => GRAMMARS[name]),
      // 浏览器端用 JS 正则引擎，省掉 Oniguruma WASM 的下载与初始化
      engine: createJavaScriptRegexEngine({ forgiving: true }),
    })
      .then((highlighter) => {
        instance = highlighter
        for (const language of highlighter.getLoadedLanguages()) loaded.add(language)
        highlightEpoch.value += 1
        return highlighter
      })
      .catch((error) => {
        // 初始化失败后不再重试，避免每次渲染都重新拉取语法
        console.warn('Shiki 初始化失败，代码块将使用纯文本渲染', error)
        started = Promise.resolve(null)
        return null
      })
  }
  return started
}

export function startHighlighter(): void {
  void ensureHighlighter()
}

export function loadedHighlighter(): HighlighterCore | null {
  return instance
}

export function isLanguageLoaded(language: string): boolean {
  return language === 'text' || loaded.has(language)
}

export async function loadLanguage(language: string): Promise<boolean> {
  const lang = normalizeLanguage(language)
  if (lang === 'text' || loaded.has(lang)) return true
  if (failed.has(lang)) return false

  const loader = grammarOf(lang)
  if (!loader) {
    failed.add(lang)
    return false
  }

  const highlighter = await ensureHighlighter()
  if (!highlighter) return false
  if (loaded.has(lang)) return true

  let task = pending.get(lang)
  if (!task) {
    task = highlighter
      .loadLanguage(loader())
      .then(() => {
        loaded.add(lang)
        highlightEpoch.value += 1
        return true
      })
      .catch(() => {
        failed.add(lang)
        return false
      })
      .finally(() => pending.delete(lang))
    pending.set(lang, task)
  }
  return task
}

export function highlightCode(code: string, language: string, plain = false): string {
  const lang = normalizeLanguage(language)
  if (plain) return `<pre><code>${escapeHtml(code)}</code></pre>`

  const key = `${lang}\u0000${code}`
  const cached = readCache(key)
  if (cached) return cached

  const highlighter = loadedHighlighter()
  if (!highlighter || !isLanguageLoaded(lang)) {
    // 语言还没就绪时先出纯文本，加载完成后 highlightEpoch 会让代码块重新渲染
    if (lang !== 'text') void loadLanguage(lang)
    return `<pre><code>${escapeHtml(code)}</code></pre>`
  }

  try {
    const html = highlighter.codeToHtml(code, {
      lang,
      themes: HIGHLIGHT_THEMES,
    })
    writeCache(key, html)
    return html
  } catch {
    return `<pre><code>${escapeHtml(code)}</code></pre>`
  }
}
