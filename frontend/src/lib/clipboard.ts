/** 复制到剪贴板：HTTP 直连这类非安全上下文没有 navigator.clipboard，退回 execCommand。 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 权限策略可能拒绝 Clipboard API，继续试 execCommand
  }

  const holder = document.createElement('textarea')
  holder.value = text
  holder.setAttribute('aria-hidden', 'true')
  holder.style.position = 'fixed'
  holder.style.top = '-9999px'
  document.body.append(holder)
  holder.select()
  try {
    return document.execCommand('copy')
  } finally {
    holder.remove()
  }
}
