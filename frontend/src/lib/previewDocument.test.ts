import { describe, expect, it } from 'vitest'

import { guardPreviewDocument } from './previewDocument'

describe('guardPreviewDocument', () => {
  it('injects the scroll guard into the document head', () => {
    const html = guardPreviewDocument(
      '<html><head><title>demo</title></head><body><p>hello</p></body></html>',
    )

    expect(html.startsWith('<!doctype html>')).toBe(true)
    expect(html).toContain('<title>demo</title>')
    expect(html).toContain('overscroll-behavior: contain')
    expect(html.indexOf('overscroll-behavior')).toBeLessThan(html.indexOf('<body'))
  })

  it('keeps fragments renderable', () => {
    const html = guardPreviewDocument('<p>hello</p>')

    expect(html).toContain('<p>hello</p>')
    expect(html).toContain('overscroll-behavior: contain')
  })

  it('does not mistake tag-like script text for the real head', () => {
    const html = guardPreviewDocument(
      '<html><head><title>demo</title></head><body><script>const s = "<head>"</script></body></html>',
    )

    expect(html).toContain('<title>demo</title>')
    expect(html).toContain('const s = "<head>"')
    expect(html.indexOf('overscroll-behavior')).toBeLessThan(html.indexOf('<body'))
  })
})
