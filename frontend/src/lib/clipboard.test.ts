import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyToClipboard } from './clipboard'

afterEach(() => {
  vi.unstubAllGlobals()
  // jsdom 不提供 execCommand，用例里是手动挂上去的
  Reflect.deleteProperty(document, 'execCommand')
})

describe('copyToClipboard', () => {
  it('uses the async Clipboard API when present', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })

    expect(await copyToClipboard('hello')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
  })

  it('falls back to execCommand without the Clipboard API', async () => {
    vi.stubGlobal('navigator', {})
    const execCommand = vi.fn(() => true)
    document.execCommand = execCommand

    expect(await copyToClipboard('hello')).toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
    // 兜底用的 textarea 用完就该收掉
    expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull()
  })

  it('reports failure when both paths fail', async () => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn(async () => {
          throw new Error('denied')
        }),
      },
    })
    document.execCommand = vi.fn(() => false)

    expect(await copyToClipboard('hello')).toBe(false)
  })
})
