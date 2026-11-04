import beautify from 'js-beautify'

export function formatHtml(source: string): string {
  const text = source.trim()
  if (!text) return ''
  try {
    return beautify.html(text, {
      indent_size: 2,
      wrap_line_length: 100,
      wrap_attributes: 'auto',
      preserve_newlines: true,
      max_preserve_newlines: 2,
      end_with_newline: true,
    })
  } catch {
    return source
  }
}
