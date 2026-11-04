import { describe, expect, it } from 'vitest'

import { ERROR_CODES, resolveErrorPage } from './errorPages'

describe('resolveErrorPage', () => {
  it.each(ERROR_CODES)('resolves supported error code %s', (code) => {
    expect(resolveErrorPage(code)).toMatchObject({ code })
  })

  it.each([undefined, null, '', '999', 'unexpected'])('falls back to 404 for %j', (code) => {
    expect(resolveErrorPage(code)).toMatchObject({ code: '404' })
  })
})
