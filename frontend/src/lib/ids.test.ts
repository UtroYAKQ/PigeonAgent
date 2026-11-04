import { afterEach, describe, expect, it, vi } from 'vitest'

import { randomUuid } from './ids'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('randomUuid', () => {
  it('uses crypto.randomUUID when available', () => {
    expect(randomUuid()).toMatch(UUID_V4)
  })

  it('falls back to getRandomValues outside secure contexts', () => {
    const { getRandomValues } = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: getRandomValues.bind(globalThis.crypto) })

    expect(randomUuid()).toMatch(UUID_V4)
  })
})
