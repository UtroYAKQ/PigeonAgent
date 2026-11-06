import { describe, expect, it } from 'vitest'

import type { SessionRun, ToolResultItem } from '@/types/api'
import { askQuestions, buildPendingBatches, isPreviewOnlyBatch } from './pending'
import { ASK_TOOL, PREVIEW_TOOL } from './frontendTools'

const now = '2026-01-01T00:00:00Z'

function itemBase(id: string) {
  return {
    id,
    in_context: false,
    display: true,
    created_at: now,
  }
}

function makeRun(content: SessionRun['content']): SessionRun {
  return {
    id: 'run-1',
    session_id: 'session-1',
    parent_run_id: null,
    seq: 1,
    status: 'interrupted',
    content,
    preview: '',
    usage: {
      requests: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      total_tokens: 0,
    },
    branch: null,
    compacted: false,
    created_at: now,
    updated_at: now,
  }
}

function resultFor(callId: string): ToolResultItem {
  return {
    ...itemBase(`result-${callId}`),
    type: 'tool_result',
    tool_call_id: callId,
    tool_name: 'demo_tool',
    content: { ok: true },
    outcome: 'success',
    metadata: null,
  }
}

describe('buildPendingBatches', () => {
  it('collects unresolved approvals and calls per interrupt', () => {
    const run = makeRun([
      {
        ...itemBase('call-1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: 'demo_tool',
        args: { value: 1 },
      },
      {
        ...itemBase('request-1'),
        type: 'approval_request',
        interrupt_id: 'interrupt-1',
        tool_call_ids: ['call-1'],
      },
      {
        ...itemBase('call-2'),
        type: 'tool_call',
        tool_call_id: 'call-2',
        tool_name: 'other_tool',
        args: { value: 2 },
      },
      {
        ...itemBase('request-2'),
        type: 'call_request',
        interrupt_id: 'interrupt-2',
        tool_call_ids: ['call-2'],
        metadata: { 'call-2': { hint: '外部结果' } },
      },
    ])

    const [approval, call] = buildPendingBatches(run, new Map())
    expect(approval?.pendingApprovals.map(item => item.toolCallId)).toEqual(['call-1'])
    expect(approval?.resolved).toBe(false)
    expect(call?.pendingCalls[0]?.metadata).toEqual({ hint: '外部结果' })
  })

  it('marks a batch resolved once every call has a result', () => {
    const run = makeRun([
      {
        ...itemBase('call-1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: 'demo_tool',
        args: {},
      },
      {
        ...itemBase('request-1'),
        type: 'approval_request',
        interrupt_id: 'interrupt-1',
        tool_call_ids: ['call-1'],
      },
    ])

    const [batch] = buildPendingBatches(run, new Map([['call-1', resultFor('call-1')]]))
    expect(batch?.resolved).toBe(true)
  })

  it('detects preview-only batches', () => {
    const run = makeRun([
      {
        ...itemBase('call-1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: PREVIEW_TOOL,
        args: { title: '预览', html: '<p>hi</p>' },
      },
      {
        ...itemBase('request-1'),
        type: 'call_request',
        interrupt_id: 'interrupt-1',
        tool_call_ids: ['call-1'],
      },
    ])

    const [batch] = buildPendingBatches(run, new Map())
    expect(batch && isPreviewOnlyBatch(batch)).toBe(true)
  })

  it('提问批次不算 preview-only，绝不自动 resume', () => {
    const run = makeRun([
      {
        ...itemBase('call-ask'),
        type: 'tool_call',
        tool_call_id: 'call-ask',
        tool_name: ASK_TOOL,
        args: {
          questions: [{ question: '先做哪个?', options: [{ label: '甲' }, { label: '乙' }] }],
        },
      },
      {
        ...itemBase('request-1'),
        type: 'call_request',
        interrupt_id: 'interrupt-1',
        tool_call_ids: ['call-ask'],
      },
    ])

    const [batch] = buildPendingBatches(run, new Map())
    // 预览可以自动打开并回填；提问必须等人选，自动 resume 会把模型的答案写成空
    expect(batch && isPreviewOnlyBatch(batch)).toBe(false)
    const tool = batch?.pendingCalls[0]
    expect(tool && askQuestions(tool)?.[0]?.options).toEqual([
      { label: '甲', description: null },
      { label: '乙', description: null },
    ])
  })

  it('问卷形状不对时退回通用结果输入', () => {
    const run = makeRun([
      {
        ...itemBase('call-ask'),
        type: 'tool_call',
        tool_call_id: 'call-ask',
        tool_name: ASK_TOOL,
        args: { questions: [] },
      },
      {
        ...itemBase('request-1'),
        type: 'call_request',
        interrupt_id: 'interrupt-1',
        tool_call_ids: ['call-ask'],
      },
    ])

    const [batch] = buildPendingBatches(run, new Map())
    const tool = batch?.pendingCalls[0]
    expect(tool && askQuestions(tool)).toBeNull()
  })
})
