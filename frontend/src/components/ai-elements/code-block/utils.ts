import type { BundledLanguage, SpecialLanguage, ThemedToken } from 'shiki'

import {
  ensureHighlighter,
  HIGHLIGHT_THEMES,
  isLanguageLoaded,
  loadLanguage,
  normalizeLanguage,
} from '@/lib/highlighter'

// Shiki uses bitflags for font styles: 1=italic, 2=bold, 4=underline
export const isItalic = (fontStyle: number | undefined) => fontStyle && fontStyle & 1
export const isBold = (fontStyle: number | undefined) => fontStyle && fontStyle & 2
export function isUnderline(fontStyle: number | undefined) {
  return fontStyle && fontStyle & 4
}

export interface TokenizedCode {
  tokens: ThemedToken[][]
  fg: string
  bg: string
}

/** 一份高亮结果对应的那段文本，调用方靠它判断新内容是不是追加。 */
export interface SettledCode {
  code: string
  language: string
  tokens: TokenizedCode
}

// 流式写入时每个增量都是新 key，不设上限会把整段中间态永久留在内存里
const CACHE_LIMIT_ENTRIES = 120
const CACHE_LIMIT_BYTES = 2 * 1024 * 1024

const tokensCache = new Map<string, TokenizedCode>()
let cacheBytes = 0

function cacheKey(code: string, language: string): string {
  return `${language}::${code}`
}

function tokenTextLength(tokens: ThemedToken[][]): number {
  let length = 0
  for (const line of tokens) {
    for (const token of line) length += token.content.length
    length += 1
  }
  return length
}

function readCache(key: string): TokenizedCode | undefined {
  const hit = tokensCache.get(key)
  if (!hit) return undefined
  // 命中后重新插入，让热点内容留在缓存里
  tokensCache.delete(key)
  tokensCache.set(key, hit)
  return hit
}

function writeCache(key: string, result: TokenizedCode): void {
  tokensCache.set(key, result)
  cacheBytes += key.length + tokenTextLength(result.tokens)
  while (cacheBytes > CACHE_LIMIT_BYTES || tokensCache.size > CACHE_LIMIT_ENTRIES) {
    const oldest = tokensCache.keys().next().value as string | undefined
    if (oldest === undefined) break
    const dropped = tokensCache.get(oldest)
    tokensCache.delete(oldest)
    cacheBytes -= oldest.length + (dropped ? tokenTextLength(dropped.tokens) : 0)
  }
}

// Create raw tokens for immediate display while highlighting loads
export function createRawTokens(code: string): TokenizedCode {
  return {
    tokens: code.split('\n').map(line =>
      line === ''
        ? []
        : [
            {
              content: line,
              color: 'inherit',
            } as ThemedToken,
          ],
    ),
    fg: 'inherit',
    bg: 'transparent',
  }
}

/** 把新追加的文本接在已高亮前缀后面：流式期不至于整块闪回纯文本。 */
export function appendRawTail(base: TokenizedCode, tail: string): TokenizedCode {
  const lines = base.tokens.slice()
  if (!lines.length) lines.push([])
  const parts = tail.split('\n')
  const first = parts.shift() ?? ''
  const last = lines.length - 1
  if (first) {
    lines[last] = [...(lines[last] ?? []), { content: first, color: 'inherit' } as ThemedToken]
  }
  for (const part of parts) {
    lines.push(part ? [{ content: part, color: 'inherit' } as ThemedToken] : [])
  }
  return { tokens: lines, fg: base.fg, bg: base.bg }
}

/** 只查缓存、不启动高亮：调用方用它决定这一帧显示什么。 */
export function peekTokens(
  code: string,
  language: BundledLanguage | SpecialLanguage,
): TokenizedCode | null {
  return readCache(cacheKey(code, normalizeLanguage(language))) ?? null
}

export async function tokenize(
  code: string,
  language: BundledLanguage | SpecialLanguage,
): Promise<TokenizedCode | null> {
  const normalized = normalizeLanguage(language)
  const tokensCacheKey = cacheKey(code, normalized)

  const cached = readCache(tokensCacheKey)
  if (cached) return cached

  const highlighter = await ensureHighlighter()
  if (!highlighter) return null
  if (!isLanguageLoaded(normalized)) await loadLanguage(normalized)

  // 等待语言加载期间可能已经有别的调用填好缓存
  const ready = readCache(tokensCacheKey)
  if (ready) return ready

  const lang = isLanguageLoaded(normalized) ? normalized : 'text'
  try {
    const result = highlighter.codeToTokens(code, {
      lang: lang as BundledLanguage | SpecialLanguage,
      themes: {
        light: HIGHLIGHT_THEMES.light,
        dark: HIGHLIGHT_THEMES.dark,
      },
    })

    const tokenized: TokenizedCode = {
      tokens: result.tokens,
      fg: result.fg ?? 'inherit',
      bg: result.bg ?? 'transparent',
    }

    writeCache(tokensCacheKey, tokenized)
    return tokenized
  } catch (error) {
    console.error('代码高亮失败:', error)
    return null
  }
}
