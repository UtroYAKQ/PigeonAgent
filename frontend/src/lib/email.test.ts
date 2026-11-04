import { describe, expect, it } from 'vitest'

import { isValidEmail } from './email'

describe('isValidEmail', () => {
  it.each([
    'user@example.com',
    'USER@Example.COM',
    'first.last+tag@example.co.uk',
    'local-user@pigeon.local',
    'user@例子.公司',
  ])('accepts %s', (value) => {
    expect(isValidEmail(value)).toBe(true)
  })

  it.each([
    'nope',
    'a@b',
    'a@b..com',
    'a@-b.com',
    'a@b-.com',
    'a@b.c',
    'a@b.123',
    'a@b.c0m',
    'a b@example.com',
    'a@b.com,',
    'a..b@example.com',
    '.a@example.com',
    'a.@example.com',
    'a@example.com.',
  ])('rejects %s', (value) => {
    expect(isValidEmail(value)).toBe(false)
  })
})
