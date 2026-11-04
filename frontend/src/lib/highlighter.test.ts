import { describe, expect, it } from 'vitest'

import { ensureHighlighter, highlightCode } from './highlighter'

const SOURCE = '{"answer": 42}'

/** Shiki 是异步初始化的，等到代码块真的带上 token 颜色为止。 */
async function renderHighlighted(): Promise<string> {
  await ensureHighlighter()
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const html = highlightCode(SOURCE, 'json')
    if (html.includes('style="color:')) return html
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error('代码块没有被高亮')
}

describe('highlightCode', () => {
  it('falls back to escaped plain text for unknown languages', () => {
    const html = highlightCode('<script>x</script>', 'not-a-language')

    expect(html).toContain('&lt;script&gt;x&lt;/script&gt;')
    expect(html).not.toContain('<script>')
  })

  it('reuses the cached highlight result', async () => {
    const highlighted = await renderHighlighted()

    expect(highlighted).toContain('"answer"')
    expect(highlightCode(SOURCE, 'json')).toBe(highlighted)
  })

  it('renders escaped plain text when asked to skip highlighting', async () => {
    await renderHighlighted()

    expect(highlightCode(SOURCE, 'json', true)).toBe(
      '<pre><code>{&quot;answer&quot;: 42}</code></pre>',
    )
  })
})
