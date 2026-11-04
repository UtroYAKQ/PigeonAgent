/** 工具把失败写进加密结果体时的 outcome 提取；只在解析出字符串时返回。 */

export function encryptedToolOutcome(value: string): string | null {
  try {
    const data = JSON.parse(value) as { pydantic_ai?: { outcome?: unknown } }
    const outcome = data.pydantic_ai?.outcome
    return typeof outcome === 'string' ? outcome : null
  } catch {
    return null
  }
}
