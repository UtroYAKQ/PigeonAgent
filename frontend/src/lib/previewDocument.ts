const GUARD_STYLE = 'html, body { overscroll-behavior: contain; }'

/**
 * 给预览文档注入守卫样式。
 * 直接改原字符串容易把 doctype / 片段结构弄坏，这里让浏览器先解析再序列化。
 */
export function guardPreviewDocument(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const style = doc.createElement('style')
  style.textContent = GUARD_STYLE
  doc.head.append(style)
  return `<!doctype html>${doc.documentElement.outerHTML}`
}
