import { describe, expect, it } from 'vitest'

import type { BundledLanguage } from 'shiki'

import { appendRawTail, createRawTokens, peekTokens, tokenize } from './utils'

const textOf = (tokens: { content: string }[][]): string[] =>
  tokens.map(line => line.map(token => token.content).join(''))

describe('appendRawTail', () => {
  it('extends the last line when the prefix stops mid-line', () => {
    const base = createRawTokens('<div>ti')
    const merged = appendRawTail(base, 'tle</div>')

    expect(textOf(merged.tokens)).toEqual(['<div>title</div>'])
  })

  it('adds new lines for a multi-line tail, keeping blank lines empty', () => {
    const base = createRawTokens('a\nb')
    const merged = appendRawTail(base, '\n\nc')

    expect(textOf(merged.tokens)).toEqual(['a', 'b', '', 'c'])
  })

  it('keeps the prefix colors untouched', () => {
    const base = createRawTokens('x')
    const merged = appendRawTail(base, 'y')

    expect(merged.tokens[0]![0]!.color).toBe('inherit')
    expect(merged.fg).toBe(base.fg)
    expect(merged.bg).toBe(base.bg)
  })
})

describe('tokenize', () => {
  it('caches the result and peeks it back synchronously', async () => {
    const code = '{"answer": 42}'

    const first = await tokenize(code, 'json')
    expect(first?.tokens.length).toBe(1)
    expect(peekTokens(code, 'json')).toBe(first)
  })

  it('falls back to plain tokens for an unknown language', async () => {
    const result = await tokenize('whatever', 'not-a-language' as BundledLanguage)

    expect(result).not.toBeNull()
    expect(result!.tokens.flat().every(token => !token.color || token.color === 'inherit')).toBe(true)
  })
})
