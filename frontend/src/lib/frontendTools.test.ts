import { describe, expect, it } from 'vitest'

import { ASK_TOOL, askAnswersPayload, FRONTEND_TOOLS, parseAskArgs } from './frontendTools'

/** 当年 mock 库里真实跑过的一份调用参数，形状就是这张卡的契约。 */
const HISTORICAL_ARGS = {
  questions: [
    {
      question: '这一步先做什么?',
      options: [
        { label: 'A 写脚本', description: '先把逻辑跑通，验证可行性' },
        { label: 'B 画原型', description: '先定形态，再谈实现' },
      ],
    },
    {
      question: '要不要顺手补测试?',
      options: [
        { label: '单元测试', description: '覆盖主流程就行' },
        { label: '端到端', description: '慢一点但更稳' },
        { label: '先不补', description: '手工验过再算' },
      ],
      multi_select: true,
    },
  ],
}

describe('ui_ask_user_question 声明', () => {
  it('随工具清单一起上报给模型', () => {
    expect(FRONTEND_TOOLS.map(tool => tool.name)).toContain(ASK_TOOL)
  })

  it('工具名符合后端对 OpenAI 兼容命名的约束', () => {
    expect(ASK_TOOL).toMatch(/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/)
  })
})

describe('parseAskArgs', () => {
  it('还原历史契约：多题、选项说明、多选标记', () => {
    const questions = parseAskArgs(HISTORICAL_ARGS)
    expect(questions).not.toBeNull()
    expect(questions).toHaveLength(2)
    expect(questions?.[0]).toEqual({
      question: '这一步先做什么?',
      multiSelect: false,
      options: [
        { label: 'A 写脚本', description: '先把逻辑跑通，验证可行性' },
        { label: 'B 画原型', description: '先定形态，再谈实现' },
      ],
    })
    expect(questions?.[1]?.multiSelect).toBe(true)
    expect(questions?.[1]?.options).toHaveLength(3)
  })

  it('也接受字符串形式的参数与纯文字选项', () => {
    const questions = parseAskArgs(
      JSON.stringify({ questions: [{ question: '要哪个?', options: ['甲', '乙'] }] }),
    )
    expect(questions).toEqual([
      {
        question: '要哪个?',
        multiSelect: false,
        options: [
          { label: '甲', description: null },
          { label: '乙', description: null },
        ],
      },
    ])
  })

  it('形状不对就整份作废，交给通用结果输入', () => {
    expect(parseAskArgs(null)).toBeNull()
    expect(parseAskArgs({})).toBeNull()
    expect(parseAskArgs({ questions: [] })).toBeNull()
    expect(parseAskArgs({ questions: [{ question: '' , options: ['甲'] }] })).toBeNull()
    expect(parseAskArgs({ questions: [{ question: '要哪个?' }] })).toBeNull()
    expect(parseAskArgs({ questions: [{ question: '要哪个?', options: [] }] })).toBeNull()
    expect(
      parseAskArgs({ questions: [{ question: '要哪个?', options: [{ description: '没有标签' }] }] }),
    ).toBeNull()
  })
})

describe('askAnswersPayload', () => {
  it('回填 {answers:[{question,selected}]}，漏答的题回空数组', () => {
    const questions = parseAskArgs(HISTORICAL_ARGS)
    if (!questions) throw new Error('历史参数应当能解析成问卷')
    const payload = askAnswersPayload(questions, { 0: ['A 写脚本'], 1: ['端到端', '先不补'] })
    expect(payload).toEqual({
      answers: [
        { question: '这一步先做什么?', selected: ['A 写脚本'] },
        { question: '要不要顺手补测试?', selected: ['端到端', '先不补'] },
      ],
    })
    expect(askAnswersPayload(questions, {}).answers[0]?.selected).toEqual([])
  })
})
