import { describe, expect, it } from 'vitest'

import type { LiveRun, SessionRun } from '@/types/api'
import { buildTurnView } from './turnModel'

const now = '2026-01-01T00:00:00Z'

const usage = {
  requests: 0,
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  total_tokens: 0,
}

function run(content: SessionRun['content'], status: SessionRun['status'] = 'completed'): SessionRun {
  return {
    id: 'run-1',
    session_id: 'session-1',
    parent_run_id: null,
    seq: 1,
    status,
    kind: 'turn',
    content,
    preview: '',
    usage,
    branch: null,
    compacted: false,
    created_at: now,
    updated_at: now,
  }
}

function base(id: string) {
  return { id, in_context: true, display: true, created_at: now }
}

function liveRun(blocks: LiveRun['blocks'], finished = false): LiveRun {
  return {
    runId: 'run-1',
    sessionId: 'session-1',
    blocks,
    usage: null,
    compaction: null,
    error: null,
    connected: true,
    finished,
  }
}

function chainTexts(view: ReturnType<typeof buildTurnView>): string[] {
  return view.segments.flatMap(segment => (
    segment.kind === 'chain'
      ? segment.entries.flatMap(entry => (entry.kind === 'reasoning' ? [entry.text] : []))
      : []
  ))
}

describe('buildTurnView', () => {
  it('groups user text, reasoning, steps and assistant text', () => {
    const view = buildTurnView(
      run([
        { ...base('u1'), type: 'text', role: 'user', text: '你好' },
        { ...base('t1'), type: 'thinking', text: '先想一想' },
        {
          ...base('c1'),
          type: 'tool_call',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          args: { name: 'a.md' },
        },
        {
          ...base('r1'),
          type: 'tool_result',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          content: { content: 'ok' },
          outcome: 'success',
        },
        { ...base('a1'), type: 'text', role: 'assistant', text: '完成' },
      ]),
      null,
    )

    expect(view.userText).toBe('你好')
    expect(view.segments.map(segment => segment.kind)).toEqual(['chain', 'text'])
    expect(chainTexts(view)).toEqual(['先想一想'])
    expect(view.assistantText).toBe('完成')
    expect(view.steps).toHaveLength(1)
    expect(view.steps[0]?.state).toBe('success')
    expect(view.sources).toEqual([])
  })

  it('keeps every reasoning segment in stream order between tool steps', () => {
    const view = buildTurnView(
      run([
        { ...base('u1'), type: 'text', role: 'user', text: '查一下' },
        { ...base('t1'), type: 'thinking', text: '先看需求' },
        {
          ...base('c1'),
          type: 'tool_call',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          args: { name: 'a.md' },
        },
        {
          ...base('r1'),
          type: 'tool_result',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          content: { content: 'ok' },
          outcome: 'success',
        },
        { ...base('t2'), type: 'thinking', text: '再看结果' },
        {
          ...base('c2'),
          type: 'tool_call',
          tool_call_id: 'call-2',
          tool_name: 'run_command',
          args: { command: 'ls' },
        },
        {
          ...base('r2'),
          type: 'tool_result',
          tool_call_id: 'call-2',
          tool_name: 'run_command',
          content: { stdout: 'a.md' },
          outcome: 'success',
        },
        { ...base('t3'), type: 'thinking', text: '可以回答了' },
        { ...base('a1'), type: 'text', role: 'assistant', text: '完成' },
      ]),
      null,
    )

    expect(view.segments).toHaveLength(2)
    const [chain] = view.segments
    expect(chain?.kind).toBe('chain')
    expect(chain?.kind === 'chain' ? chain.entries.map(entry => entry.kind) : []).toEqual([
      'reasoning',
      'tool',
      'reasoning',
      'tool',
      'reasoning',
    ])
    expect(chainTexts(view)).toEqual(['先看需求', '再看结果', '可以回答了'])
    expect(view.steps.map(step => step.id)).toEqual(['call-1', 'call-2'])
  })

  it('starts a new chain after assistant body text', () => {
    const view = buildTurnView(
      run([
        { ...base('t1'), type: 'thinking', text: '第一段推理' },
        {
          ...base('c1'),
          type: 'tool_call',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          args: { name: 'a.md' },
        },
        {
          ...base('r1'),
          type: 'tool_result',
          tool_call_id: 'call-1',
          tool_name: 'read_file',
          content: { content: 'ok' },
          outcome: 'success',
        },
        { ...base('a1'), type: 'text', role: 'assistant', text: '中间回答' },
        { ...base('t2'), type: 'thinking', text: '第二段推理' },
        {
          ...base('c2'),
          type: 'tool_call',
          tool_call_id: 'call-2',
          tool_name: 'run_command',
          args: { command: 'ls' },
        },
        {
          ...base('r2'),
          type: 'tool_result',
          tool_call_id: 'call-2',
          tool_name: 'run_command',
          content: { stdout: 'a.md' },
          outcome: 'success',
        },
        { ...base('a2'), type: 'text', role: 'assistant', text: '最终回答' },
      ]),
      null,
    )

    expect(view.segments.map(segment => segment.kind)).toEqual([
      'chain',
      'text',
      'chain',
      'text',
    ])
    expect(chainTexts(view)).toEqual(['第一段推理', '第二段推理'])
    const texts = view.segments.flatMap(segment => (segment.kind === 'text' ? [segment.text] : []))
    expect(texts).toEqual(['中间回答', '最终回答'])
    expect(view.assistantText).toBe('中间回答\n\n最终回答')
  })

  it('uses live blocks while streaming', () => {
    const view = buildTurnView(
      run([], 'running'),
      liveRun([
        { id: 'text-1', kind: 'text', text: '流式', streaming: true },
        { id: 'reason-1', kind: 'reasoning', text: '思考', streaming: true },
      ]),
    )

    expect(view.status).toBe('streaming')
    expect(view.assistantText).toBe('流式')
    expect(view.segments.map(segment => segment.kind)).toEqual(['text', 'chain'])
    expect(view.segments[0]?.kind === 'text' ? view.segments[0].streaming : null).toBe(false)
    const chain = view.segments[1]
    expect(chain?.kind).toBe('chain')
    if (chain?.kind === 'chain') {
      expect(chain.streaming).toBe(true)
      expect(chain.entries[0]?.kind === 'reasoning' ? chain.entries[0].text : null).toBe('思考')
    }
  })

  it('keeps live reasoning segments interleaved with tool calls', () => {
    const view = buildTurnView(
      run([], 'running'),
      liveRun([
        { id: 'reason-1', kind: 'reasoning', text: '第一段', streaming: false },
        {
          id: 'call-1',
          kind: 'tool',
          tool: { toolCallId: 'call-1', name: 'read_file', argsText: '{"name":"a.md"}', state: 'success' },
        },
        { id: 'reason-2', kind: 'reasoning', text: '第二段', streaming: true },
        {
          id: 'call-2',
          kind: 'tool',
          tool: { toolCallId: 'call-2', name: 'run_command', argsText: '{"command":"ls"}', state: 'running' },
        },
      ]),
    )

    expect(view.segments).toHaveLength(1)
    const [chain] = view.segments
    expect(chain?.kind === 'chain' ? chain.entries.map(entry => entry.kind) : []).toEqual([
      'reasoning',
      'tool',
      'reasoning',
      'tool',
    ])
    expect(view.steps.map(step => step.id)).toEqual(['call-1', 'call-2'])
    expect(view.steps[1]?.state).toBe('running')
  })

  it('splits live chains at streamed text', () => {
    const view = buildTurnView(
      run([], 'running'),
      liveRun([
        { id: 'reason-1', kind: 'reasoning', text: '先查', streaming: false },
        {
          id: 'call-1',
          kind: 'tool',
          tool: { toolCallId: 'call-1', name: 'read_file', argsText: '{"name":"a.md"}', state: 'success' },
        },
        { id: 'text-1', kind: 'text', text: '中间回答', streaming: false },
        { id: 'reason-2', kind: 'reasoning', text: '再查', streaming: false },
        {
          id: 'call-2',
          kind: 'tool',
          tool: { toolCallId: 'call-2', name: 'run_command', argsText: '{"command":"ls"}', state: 'success' },
        },
        { id: 'text-2', kind: 'text', text: '最终回答', streaming: true },
      ]),
    )

    expect(view.segments.map(segment => segment.kind)).toEqual([
      'chain',
      'text',
      'chain',
      'text',
    ])
    expect(view.assistantText).toBe('中间回答\n\n最终回答')
    expect(view.segments[1]?.kind === 'text' ? view.segments[1].streaming : null).toBe(false)
    expect(view.segments[2]?.kind === 'chain' ? view.segments[2].streaming : null).toBe(false)
    expect(view.segments[3]?.kind === 'text' ? view.segments[3].streaming : null).toBe(true)
  })

  it('marks unfinished steps interrupted when the run was cancelled', () => {
    const view = buildTurnView(
      run(
        [
          {
            ...base('c1'),
            type: 'tool_call',
            tool_call_id: 'call-1',
            tool_name: 'run_command',
            args: { command: 'ls' },
          },
        ],
        'cancelled',
      ),
      null,
    )
    expect(view.cancelled).toBe(true)
    expect(view.steps[0]?.state).toBe('interrupted')
  })

  it('never leaves unfinished tools running after the run is over', () => {
    const call = {
      ...base('c1'),
      type: 'tool_call' as const,
      tool_call_id: 'call-1',
      tool_name: 'web_search',
      args: { query: 'agui 是什么' },
    }

    // completed 却缺 result 属于数据异常：显示失败回执，而不是误导性的“已暂停”
    const completed = buildTurnView(run([call], 'completed'), null)
    expect(completed.steps[0]?.state).toBe('failed')
    expect(completed.steps[0]?.label).toBe('搜索失败')

    const failed = buildTurnView(run([call], 'failed'), null)
    expect(failed.steps[0]?.state).toBe('failed')
    expect(failed.steps[0]?.label).toBe('搜索失败')
  })

  it('keeps a generated image in place when tools run in parallel', () => {
    const call = (id: string, name: string, args: unknown) => ({
      ...base(id),
      type: 'tool_call' as const,
      tool_call_id: id,
      tool_name: name,
      args,
    })
    const result = (id: string, name: string) => ({
      ...base(`r-${id}`),
      type: 'tool_result' as const,
      tool_call_id: id,
      tool_name: name,
      content: { ok: true },
      outcome: 'success' as const,
      metadata: null,
    })
    const image = {
      ...base('img-1'),
      type: 'image' as const,
      role: 'assistant' as const,
      file_id: 'a'.repeat(32),
      data: null,
      url: null,
      media_type: 'image/png',
      alt: '雪山日出',
    }

    const view = buildTurnView(
      run([
        { ...base('t1'), type: 'text' as const, role: 'assistant' as const, text: '先查天气再出图。' },
        call('img', 'generate_image', { prompt: '雪山日出' }),
        call('search', 'web_search', { query: '丽江天气' }),
        // 搜索先回来，图片后回来：产物要落在图片生成的那一刻
        result('search', 'web_search'),
        result('img', 'generate_image'),
        image,
        { ...base('t2'), type: 'text' as const, role: 'assistant' as const, text: '都好了。' },
      ]),
      null,
    )

    expect(view.segments.map(segment => segment.kind)).toEqual(['text', 'chain', 'artifact', 'text'])
    const artifact = view.segments[2]
    expect(artifact?.kind === 'artifact' && artifact.media[0]?.fileId).toBe('a'.repeat(32))
    // 两个工具在同一条链里，产物不能把链切断成两段
    expect(view.steps).toHaveLength(2)
  })

  it('merges consecutive generated images into one artifact block', () => {
    const image = (id: string) => ({
      ...base(id),
      type: 'image' as const,
      role: 'assistant' as const,
      file_id: id.padEnd(32, '0'),
      data: null,
      url: null,
      media_type: 'image/png',
      alt: null,
    })

    const view = buildTurnView(
      run([image('a'), image('b'), image('c'), image('d')]),
      null,
    )

    expect(view.segments).toHaveLength(1)
    const artifact = view.segments[0]
    expect(artifact?.kind === 'artifact' && artifact.media).toHaveLength(4)
  })

  it('routes published files to attachments and images to the body', () => {
    const resource = (id: string, mediaType: string) => ({
      ...base(id),
      type: 'resource' as const,
      role: 'assistant' as const,
      storage_key: id.padEnd(32, '0'),
      media_type: mediaType,
      name: `${id}.dat`,
      size: 1024,
    })

    const view = buildTurnView(
      run([
        { ...base('t1'), type: 'text' as const, role: 'assistant' as const, text: '文件给你。' },
        resource('r1', 'text/plain'),
        resource('r2', 'image/png'),
      ]),
      null,
    )

    // 图片在正文看，文件只在末尾清单里拿，不要两处都出现
    expect(view.segments.map(segment => segment.kind)).toEqual(['text', 'artifact'])
    expect(view.attachments.map(item => item.name)).toEqual(['r1.dat'])
    const artifact = view.segments[1]
    expect(artifact?.kind === 'artifact' && artifact.media[0]?.name).toBe('r2.dat')
  })

  it('hides a successful image step from the chain but keeps failures', () => {
    const call = {
      ...base('c1'),
      type: 'tool_call' as const,
      tool_call_id: 'call-1',
      tool_name: 'generate_image',
      args: { prompt: '雪山' },
    }
    const image = {
      ...base('i1'),
      type: 'image' as const,
      role: 'assistant' as const,
      file_id: 'a'.repeat(32),
      data: null,
      url: null,
      media_type: 'image/png',
      alt: '雪山',
    }

    const done = {
      ...base('r1'),
      type: 'tool_result' as const,
      tool_call_id: 'call-1',
      tool_name: 'generate_image',
      content: { ok: true, count: 1 },
      outcome: 'success' as const,
      metadata: null,
    }

    const ok = buildTurnView(run([call, done, image]), null)
    // 出图成功时链里不留步骤，产物本身就是反馈
    expect(ok.segments.every(segment => segment.kind !== 'chain')).toBe(true)

    const failed = buildTurnView(run([call], 'failed'), null)
    expect(failed.segments.some(segment => segment.kind === 'chain')).toBe(true)
  })

  it('flags in-flight image generation so the skeleton can stand in', () => {
    const live = buildTurnView(
      run([], 'running'),
      liveRun([
        {
          id: 'b1',
          kind: 'tool',
          tool: { toolCallId: 'c1', name: 'generate_image', argsText: '{}', state: 'running' },
        },
      ]),
    )
    expect(live.generatingImage).toBe(true)
    expect(live.segments).toHaveLength(0)

    const idle = buildTurnView(run([], 'running'), liveRun([]))
    expect(idle.generatingImage).toBe(false)
  })

  it('keeps the artifact card when reasoning resumes under the same message id', () => {
    // 出图后模型常带同一个 messageId 继续想：两段 chain 的 key 撞车，
    // Vue 会把夹在中间的产物卡直接从 DOM 里挤掉（刷新才回来）。
    const view = buildTurnView(
      run([], 'running'),
      liveRun([
        { id: 'reason-1', kind: 'reasoning', text: '先定构图', streaming: false },
        {
          id: 'call-1',
          kind: 'tool',
          tool: {
            toolCallId: 'call-1',
            name: 'generate_image',
            argsText: '{}',
            state: 'success',
            resultText: '{"file_id":"a"}',
          },
        },
        {
          id: 'artifact-a',
          kind: 'artifact',
          media: [
            {
              file_id: 'a'.repeat(32),
              media_type: 'image/png',
              name: '雪山.png',
              size: 1024,
              alt: '雪山',
              origin: 'generated',
            },
          ],
        },
        { id: 'reason-1', kind: 'reasoning', text: '图已经出来了', streaming: true },
      ]),
    )

    expect(view.segments.map(segment => segment.kind)).toEqual(['chain', 'artifact', 'chain'])
    const ids = view.segments.map(segment => segment.id)
    expect(new Set(ids).size).toBe(ids.length)
    if (view.segments[2]?.kind === 'chain') {
      expect(view.segments[2].entries[0]?.kind === 'reasoning'
        ? view.segments[2].entries[0].text
        : null).toBe('图已经出来了')
    }
  })

  it('collects search results with their site icons without treating icons as sources', () => {
    const view = buildTurnView(
      run([
        { ...base('u1'), type: 'text', role: 'user', text: '搜一下' },
        {
          ...base('c1'),
          type: 'tool_call',
          tool_call_id: 'call-1',
          tool_name: 'web_search',
          args: { query: 'dify' },
        },
        {
          ...base('r1'),
          type: 'tool_result',
          tool_call_id: 'call-1',
          tool_name: 'web_search',
          outcome: 'success',
          content: {
            query: 'dify',
            results: [
              {
                title: 'Dify Docs',
                url: 'https://docs.dify.ai/guide',
                site_icon: 'https://cdn.deepseek.com/site-icons/dify.ai',
              },
              {
                title: 'Dify Docs again',
                url: 'https://docs.dify.ai/guide',
                site_icon: 'https://cdn.deepseek.com/site-icons/dify.ai',
              },
              { title: 'Example', url: 'https://example.com/a' },
            ],
          },
        },
      ]),
      null,
    )

    expect(view.sources).toEqual([
      { url: 'https://docs.dify.ai/guide', icon: 'https://cdn.deepseek.com/site-icons/dify.ai' },
      { url: 'https://example.com/a', icon: null },
    ])
  })
})
