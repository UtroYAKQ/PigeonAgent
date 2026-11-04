import { describe, expect, it } from 'vitest'

import { plainTextFromMarkdown } from './markdown'

describe('plainTextFromMarkdown', () => {
  it('strips fences, inline code, links and images', () => {
    const source = [
      '## 标题',
      '',
      '![截图](https://example.com/a.png)',
      '',
      '看 [`code`](https://example.com) 和 **加粗**。',
      '',
      '```js',
      'const a = 1',
      '```',
    ].join('\n')

    const text = plainTextFromMarkdown(source)

    expect(text).toContain('标题')
    expect(text).toContain('code')
    expect(text).toContain('加粗')
    expect(text).toContain('const a = 1')
    expect(text).not.toContain('example.com')
    expect(text).not.toContain('```')
  })

  it('collapses runs of blank lines', () => {
    expect(plainTextFromMarkdown('第一段\n\n\n\n第二段')).toBe('第一段\n\n第二段')
  })
})
