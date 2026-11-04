/**
 * 密码规则的唯一来源，口径跟后端 app/schemas/user.py 的 Password 一致：
 * 注册、改密、管理员重置三条写入路径用的都是同一个类型约束。
 */
const MIN_CHARS = 8
// bcrypt 只处理前 72 字节，超出的部分会被静默截断；
// 不在这里挡住，用户会以为密码是「那串长密码」，实际能用的是被截断的前 72 字节。
const MAX_BYTES = 72

/**
 * 校验要写入数据库的新密码，返回要展示给用户的中文提示；合格返回 null。
 * 登录/校验当前密码不走这里——后端对它们只要求非空（PasswordInput）。
 *
 * 字符数按 Unicode 码点算，和 Python 的 len() 同口径：
 * 按 UTF-16 的 length 算会让 emoji 密码在前后端得出相反结论。
 */
export function validateNewPassword(value: string): string | null {
  if (Array.from(value).length < MIN_CHARS) return `密码至少需要 ${MIN_CHARS} 个字符`
  if (new TextEncoder().encode(value).length > MAX_BYTES) {
    return `密码不能超过 ${MAX_BYTES} 个字节（UTF-8）`
  }
  return null
}
