// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./authStorage', () => ({ accessToken: () => null }))
vi.mock('./http', () => ({ refreshAccessToken: vi.fn() }))

import type { AgUiEvent } from '@/types/api'
import { streamRun } from './sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('streamRun', () => {
  it('parses frames split across chunks and flushes the final frame', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          streamOf([
            'id: 1\ndata: {"type":"RUN_STARTED"}\n\nid: 2\ndata: {"type":"TEXT_MESSAGE_CONTENT","delta":"你',
            '好"}\n\n',
            'id: 3\ndata: {"type":"TEXT_MESSAGE_END"}',
          ]),
          { status: 200 },
        ),
      ),
    )

    const events: AgUiEvent[] = []
    const sequences: number[] = []
    await streamRun({
      url: '/events',
      signal: new AbortController().signal,
      onEvent: event => events.push(event),
      onSequence: value => sequences.push(value),
    })

    expect(events.map(event => event.type)).toEqual([
      'RUN_STARTED',
      'TEXT_MESSAGE_CONTENT',
      'TEXT_MESSAGE_END',
    ])
    const content = events[1]
    if (content?.type !== 'TEXT_MESSAGE_CONTENT') throw new Error('第二帧应该是文本增量事件')
    expect(content.delta).toBe('你好')
    expect(sequences).toEqual([1, 2, 3])
  })

  it('throws when the stream is gone', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 410 })))
    await expect(
      streamRun({
        url: '/events',
        signal: new AbortController().signal,
        onEvent: () => undefined,
      }),
    ).rejects.toThrow('运行已结束')
  })
})
