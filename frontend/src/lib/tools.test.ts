import { describe, expect, it } from 'vitest'

import type { RunItem } from '@/types/api'
import { buildToolSteps, fileLanguage } from './tools'

const now = '2026-01-01T00:00:00Z'

function base(id: string) {
  return { id, in_context: true, display: true, created_at: now }
}

describe('buildToolSteps', () => {
  it('marks a failed outcome as failed', () => {
    const items: RunItem[] = [
      {
        ...base('c1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: 'run_command',
        args: { command: 'pytest -q' },
      },
      {
        ...base('r1'),
        type: 'tool_result',
        tool_call_id: 'call-1',
        tool_name: 'run_command',
        content: { exit_code: 1, stdout: '', stderr: 'failed' },
        outcome: 'failed',
      },
    ]

    const steps = buildToolSteps(items)
    expect(steps[0]?.state).toBe('failed')
    expect(steps[0]?.label).toBe('代码运行失败')
  })

  it('marks a denied outcome as failed', () => {
    const items: RunItem[] = [
      {
        ...base('c1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: 'delete_file',
        args: { path: 'tmp/cache.log' },
      },
      {
        ...base('r1'),
        type: 'tool_result',
        tool_call_id: 'call-1',
        tool_name: 'delete_file',
        content: '用户拒绝了这次调用',
        outcome: 'denied',
      },
    ]

    expect(buildToolSteps(items)[0]?.state).toBe('failed')
  })

  it('keeps a successful outcome successful', () => {
    const items: RunItem[] = [
      {
        ...base('c1'),
        type: 'tool_call',
        tool_call_id: 'call-1',
        tool_name: 'run_command',
        args: { command: 'ls' },
      },
      {
        ...base('r1'),
        type: 'tool_result',
        tool_call_id: 'call-1',
        tool_name: 'run_command',
        content: { exit_code: 0, stdout: 'a.md', stderr: '' },
        outcome: 'success',
      },
    ]

    expect(buildToolSteps(items)[0]?.state).toBe('success')
  })
})

describe('fileLanguage', () => {
  it('prefers the file extension once the name is known', () => {
    expect(fileLanguage('about.HTML', '<p>hi</p>')).toBe('html')
    expect(fileLanguage('app.py', 'import os')).toBe('python')
    expect(fileLanguage('notes', '# 标题')).toBe('markdown')
  })

  it('sniffs the language from content before the name arrives', () => {
    expect(fileLanguage(null, '<!doctype html>\n<html lang="zh-CN">')).toBe('html')
    expect(fileLanguage(null, '{\n  "a": 1\n}')).toBe('json')
    expect(fileLanguage(null, ':root { --bg: #fff; }')).toBe('css')
    expect(fileLanguage(null, 'from pathlib import Path')).toBe('python')
    expect(fileLanguage(null, 'export const app = 1')).toBe('typescript')
    expect(fileLanguage(null, '<catalog><book/></catalog>')).toBe('xml')
  })

  it('stays plain text when nothing identifies the content', () => {
    expect(fileLanguage(null, '')).toBe('text')
    expect(fileLanguage(null, '随便一段话')).toBe('text')
    expect(fileLanguage('LICENSE', 'Copyright')).toBe('text')
  })
})
