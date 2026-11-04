import { describe, expect, it } from 'vitest'

import { validateNewPassword } from '@/lib/password'

// 后端 app/schemas/user.py：Password = min_length 8 且 UTF-8 字节数 ≤ 72
describe('validateNewPassword', () => {
  it('接受后端也会接受的密码', () => {
    expect(validateNewPassword('pigeon-ai')).toBeNull()
    expect(validateNewPassword('12345678')).toBeNull()
  })

  it('短于 8 个字符就拒绝', () => {
    expect(validateNewPassword('')).toMatch(/至少需要 8 个字符/)
    expect(validateNewPassword('abc')).toMatch(/至少需要 8 个字符/)
  })

  it('8 个中文是 24 字节，仍在上限内', () => {
    expect(validateNewPassword('鸽子飞行密码八位')).toBeNull()
  })

  // 这条正是修复的动机：字符数合规但字节超限，前端放行、后端 422
  it('超过 72 字节就拒绝，哪怕字符数不多', () => {
    expect(validateNewPassword('字'.repeat(25))).toMatch(/72 个字节/)
    expect(validateNewPassword('字'.repeat(24))).toBeNull()
  })

  it('按码点计字符数，不按 UTF-16 长度', () => {
    // 4 个 emoji 的 length 是 8，但后端 len() 只有 4
    expect(validateNewPassword('🐦🐦🐦🐦')).toMatch(/至少需要 8 个字符/)
  })
})
