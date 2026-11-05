import { describe, expect, it } from 'vitest'

import type { AgUiEvent, LiveMedia, LiveRun } from '@/types/api'
import { applyAgUiEvent } from './agui'

function liveRun(): LiveRun {
  return {
    runId: 'run-1',
    sessionId: 'session-1',
    blocks: [],
    usage: null,
    compaction: null,
    error: null,
    connected: false,
    finished: false,
  }
}

function apply(...events: AgUiEvent[]): LiveRun {
  const live = liveRun()
  for (const event of events) applyAgUiEvent(live, event)
  return live
}

function blockOf(live: LiveRun, id: string) {
  return live.blocks.find(item => item.id === id)
}

const usage = {
  requests: 1,
  input_tokens: 10,
  output_tokens: 20,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  total_tokens: 30,
}

function generated(fileId: string) {
  return {
    storage_key: fileId,
    file_name: `${fileId}.png`,
    media_type: 'image/png',
    size: 1024,
    alt: null,
  }
}

function media(fileId: string): LiveMedia {
  return { file_id: fileId, media_type: 'image/png', name: `${fileId}.png`, size: 1024, alt: null }
}

describe('applyAgUiEvent run 生命周期', () => {
  it('RUN_STARTED 只把连接标记为已建立', () => {
    const live = apply({ type: 'RUN_STARTED', threadId: 'session-1', runId: 'run-1' })
    expect(live).toMatchObject({ connected: true, finished: false, blocks: [] })
  })

  it('RUN_FINISHED 收尾并清掉还在跑的压缩状态', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'compaction_start', value: { estimated_tokens: 900 } },
      { type: 'RUN_FINISHED', threadId: 'session-1', runId: 'run-1' },
    )
    expect(live).toMatchObject({ finished: true, compaction: null })
  })

  it('RUN_ERROR 记下错误、收尾并清掉压缩状态', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'compaction_start', value: { estimated_tokens: 900 } },
      { type: 'RUN_ERROR', message: '上游超时', code: 'timeout' },
    )
    expect(live).toMatchObject({ error: '上游超时', errorCode: 'timeout', finished: true, compaction: null })
  })

  it('RUN_ERROR 没有消息时留一句可诊断的兜底', () => {
    expect(apply({ type: 'RUN_ERROR', message: '' }).error).toBe('运行失败')
  })
})

describe('applyAgUiEvent 思考流', () => {
  it('REASONING_START 与 REASONING_MESSAGE_START 共用同一个思考块', () => {
    const live = apply(
      { type: 'REASONING_START', messageId: 'think-1' },
      { type: 'REASONING_MESSAGE_START', messageId: 'think-1' },
    )
    expect(blockOf(live, 'think-1')).toMatchObject({ kind: 'reasoning', text: '', streaming: true })
    expect(live.blocks).toHaveLength(1)
  })

  it('REASONING_MESSAGE_CONTENT 累加增量，缺 start 也能自建块', () => {
    const live = apply(
      { type: 'REASONING_MESSAGE_CONTENT', messageId: 'think-1', delta: '先' },
      { type: 'REASONING_MESSAGE_CONTENT', messageId: 'think-1', delta: '想' },
    )
    expect(blockOf(live, 'think-1')).toMatchObject({ kind: 'reasoning', text: '先想', streaming: true })
  })

  it('没有 messageId 的思考事件落到 reasoning 这个固定块上', () => {
    const live = apply({ type: 'REASONING_MESSAGE_CONTENT', delta: '无主增量' })
    expect(blockOf(live, 'reasoning')?.text).toBe('无主增量')
  })

  it('REASONING_END 与 REASONING_MESSAGE_END 都只关流，不删内容', () => {
    const live = apply(
      { type: 'REASONING_MESSAGE_START', messageId: 'think-1' },
      { type: 'REASONING_MESSAGE_CONTENT', messageId: 'think-1', delta: '想过' },
      { type: 'REASONING_MESSAGE_END', messageId: 'think-1' },
      { type: 'REASONING_END', messageId: 'think-1' },
    )
    expect(blockOf(live, 'think-1')).toMatchObject({ text: '想过', streaming: false })
  })
})

describe('applyAgUiEvent 正文流', () => {
  it('TEXT_MESSAGE_START 开块，CONTENT 累加，END 收流', () => {
    const live = apply(
      { type: 'TEXT_MESSAGE_START', messageId: 'msg-1' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: '你好' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: '，世界' },
      { type: 'TEXT_MESSAGE_END', messageId: 'msg-1' },
    )
    expect(blockOf(live, 'msg-1')).toMatchObject({ kind: 'text', text: '你好，世界', streaming: false })
  })

  it('正文和思考各占一块，互不合并', () => {
    const live = apply(
      { type: 'REASONING_MESSAGE_CONTENT', messageId: 'think-1', delta: '想' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: '答' },
    )
    expect(live.blocks.map(item => item.kind)).toEqual(['reasoning', 'text'])
  })
})

describe('applyAgUiEvent 工具调用', () => {
  const start = { type: 'TOOL_CALL_START', toolCallId: 'call-1', toolCallName: 'run_command' } as const

  it('TOOL_CALL_START 建一个 running 块，重复的 START 不再建第二个', () => {
    const live = apply(start, start)
    expect(live.blocks).toHaveLength(1)
    expect(blockOf(live, 'call-1')?.tool).toMatchObject({ name: 'run_command', state: 'running', argsText: '' })
  })

  it('TOOL_CALL_ARGS 拼参数，TOOL_CALL_END 把 running 收成 waiting', () => {
    const live = apply(
      start,
      { type: 'TOOL_CALL_ARGS', toolCallId: 'call-1', delta: '{"command":' },
      { type: 'TOOL_CALL_ARGS', toolCallId: 'call-1', delta: '"ls"}' },
      { type: 'TOOL_CALL_END', toolCallId: 'call-1' },
    )
    expect(live.blocks[0]?.tool).toMatchObject({ argsText: '{"command":"ls"}', state: 'waiting' })
  })

  it('TOOL_CALL_RESULT 写回结果并记下结果消息 id', () => {
    const live = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'a.md' },
    )
    expect(live.blocks[0]?.tool).toMatchObject({ state: 'success', resultText: 'a.md', resultMessageId: 'res-1' })
  })

  it('已有结果的工具有后到的 START 不会被覆盖成 running', () => {
    const live = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'a.md' },
      start,
    )
    expect(live.blocks[0]?.tool?.state).toBe('success')
  })

  it('REASONING_ENCRYPTED_VALUE 按结果消息 id 把成功改判为失败或中断', () => {
    const outcome = (value: string) => JSON.stringify({ pydantic_ai: { outcome: value } })
    const withFailed = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'boom' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'message', entityId: 'res-1', encryptedValue: outcome('failed') },
    )
    expect(withFailed.blocks[0]?.tool?.state).toBe('failed')

    const withDenied = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'boom' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'message', entityId: 'res-1', encryptedValue: outcome('denied') },
    )
    expect(withDenied.blocks[0]?.tool?.state).toBe('failed')

    const withInterrupted = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'boom' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'message', entityId: 'res-1', encryptedValue: outcome('interrupted') },
    )
    expect(withInterrupted.blocks[0]?.tool?.state).toBe('interrupted')
  })

  it('REASONING_ENCRYPTED_VALUE 忽略 tool-call 子类型、非 outcome 载荷和陌生实体', () => {
    const live = apply(
      start,
      { type: 'TOOL_CALL_RESULT', toolCallId: 'call-1', messageId: 'res-1', content: 'ok' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'tool-call', entityId: 'call-1', encryptedValue: '{}' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'message', entityId: 'res-1', encryptedValue: 'not json' },
      { type: 'REASONING_ENCRYPTED_VALUE', subtype: 'message', entityId: 'res-unknown', encryptedValue: '{"pydantic_ai":{"outcome":"failed"}}' },
    )
    expect(live.blocks[0]?.tool?.state).toBe('success')
  })
})

describe('applyAgUiEvent CUSTOM 事件', () => {
  it('run_usage 写入用量', () => {
    expect(apply({ type: 'CUSTOM', name: 'run_usage', value: { usage } }).usage).toEqual(usage)
  })

  it('image_generated 建一个产物块', () => {
    const live = apply({ type: 'CUSTOM', name: 'image_generated', value: generated('file-1') })
    expect(blockOf(live, 'artifact-file-1')).toMatchObject({
      kind: 'artifact',
      media: [{ file_id: 'file-1', origin: 'generated' }],
    })
  })

  it('连续到达的图片并进同一块，一次出多张就是一张网格', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'image_generated', value: generated('file-1') },
      { type: 'CUSTOM', name: 'image_generated', value: generated('file-2') },
    )
    expect(live.blocks).toHaveLength(1)
    expect(live.blocks[0]?.media?.map(item => item.file_id)).toEqual(['file-1', 'file-2'])
  })

  it('artifact 建一个工作区产物块', () => {
    const live = apply({ type: 'CUSTOM', name: 'artifact', value: { media: [media('file-1')] } })
    expect(blockOf(live, 'artifact-file-1')).toMatchObject({ kind: 'artifact' })
  })

  it('连续到达的工作区产物并进同一块', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'artifact', value: { media: [media('file-1')] } },
      { type: 'CUSTOM', name: 'artifact', value: { media: [media('file-2')] } },
    )
    expect(live.blocks).toHaveLength(1)
    expect(live.blocks[0]?.media?.map(item => item.file_id)).toEqual(['file-1', 'file-2'])
  })

  it('无效的产物事件不建块，正文块之后的产物另起一块', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'image_generated', value: {} },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: '文字' },
      { type: 'CUSTOM', name: 'image_generated', value: generated('file-1') },
    )
    expect(live.blocks.map(item => item.kind)).toEqual(['text', 'artifact'])
  })

  it('compaction_start 与 compaction_result 各自建状态，结果缺 token 时沿用开始值', () => {
    const live = apply(
      { type: 'CUSTOM', name: 'compaction_start', value: { estimated_tokens: 8000 } },
      { type: 'CUSTOM', name: 'compaction_result', value: { summary: '压缩了 12 条' } },
    )
    expect(live.compaction).toEqual({ status: 'done', summary: '压缩了 12 条', tokensBefore: 8000 })
  })

  it('未知的 CUSTOM name 什么都不改', () => {
    const live = apply({ type: 'CUSTOM', name: 'something_new', value: { hello: 'world' } })
    expect(live).toEqual(liveRun())
  })
})

describe('applyAgUiEvent 未知事件', () => {
  it('协议新增但前端还没接的 type 被忽略，不破坏已有块', () => {
    const unknown = { type: 'ACTIVITY_SNAPSHOT' } as unknown as AgUiEvent
    const live = apply(
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: '文字' },
      unknown,
    )
    expect(live.blocks).toHaveLength(1)
    expect(live.finished).toBe(false)
  })
})
