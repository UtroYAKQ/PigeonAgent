/**
 * 前端只拦明显写错的地址，最终规则以后端为准。
 * 保留 .local 等内网域名，避免自建部署的默认管理员被前端挡住。
 */
const LOCAL_PART = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/
const DOMAIN_LABEL = /^[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?$/u
const LETTER_TLD = /^\p{L}{2,}$/u

export function isValidEmail(value: string): boolean {
  const email = value.trim()
  if (!email || email.length > 254) return false

  const at = email.indexOf('@')
  if (at <= 0 || at !== email.lastIndexOf('@')) return false

  const local = email.slice(0, at)
  const domain = email.slice(at + 1).toLowerCase()
  if (local.length > 64 || !LOCAL_PART.test(local)) return false
  if (domain.length > 253 || domain.endsWith('.')) return false

  const labels = domain.split('.')
  if (labels.length < 2 || !labels.every(label => DOMAIN_LABEL.test(label))) return false

  const tld = labels[labels.length - 1]
  return tld.length >= 2 && (tld.startsWith('xn--') || LETTER_TLD.test(tld))
}
