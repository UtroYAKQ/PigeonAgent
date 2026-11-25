import type { FrontendToolDecl } from '@/types/api'
import { parseJsonLike } from './format'

export const ASK_TOOL = 'ui_ask_user_question'

export const FRONTEND_TOOLS: FrontendToolDecl[] = [
  {
    name: ASK_TOOL,
    description:
      '在继续之前向用户提问并等待其选择。用于方向分歧、缺少关键信息或需要用户在若干方案中拍板时；'
      + '一次可以问多题，每题给出带简短说明的选项，multi_select 为 true 时允许多选。'
      + '结果以 {answers:[{question,selected:[…]}]} 回填，拿到答案后请据此继续。',
    parameters: {
      type: 'object',
      properties: {
        questions: {
          type: 'array',
          minItems: 1,
          items: {
            type: 'object',
            properties: {
              question: { type: 'string', description: '要问用户的问题' },
              options: {
                type: 'array',
                minItems: 1,
                items: {
                  type: 'object',
                  properties: {
                    label: { type: 'string', description: '选项文字' },
                    description: { type: 'string', description: '这个选项意味着什么，可省略' },
                  },
                  required: ['label'],
                },
              },
              multi_select: { type: 'boolean', description: '允许多选，默认单选' },
            },
            required: ['question', 'options'],
          },
        },
      },
      required: ['questions'],
    },
  },
]

export interface AskOption {
  label: string
  description: string | null
}

export interface AskQuestion {
  question: string
  options: AskOption[]
  multiSelect: boolean
}

/**
 * 把模型给的 questions 收敛成可渲染的问卷。
 * 形状不对就整份作废（返回 null），让调用方退回通用结果输入，而不是渲染半张卡。
 */
export function parseAskArgs(args: unknown): AskQuestion[] | null {
  const value = parseJsonLike(args)
  if (!value || typeof value !== 'object') return null
  const rawQuestions = (value as Record<string, unknown>).questions
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null

  const questions: AskQuestion[] = []
  for (const raw of rawQuestions) {
    if (!raw || typeof raw !== 'object') return null
    const data = raw as Record<string, unknown>
    const question = typeof data.question === 'string' ? data.question.trim() : ''
    if (!question || !Array.isArray(data.options)) return null

    const options: AskOption[] = []
    for (const rawOption of data.options) {
      if (typeof rawOption === 'string') {
        if (rawOption.trim()) options.push({ label: rawOption.trim(), description: null })
        continue
      }
      if (!rawOption || typeof rawOption !== 'object') return null
      const option = rawOption as Record<string, unknown>
      if (typeof option.label !== 'string' || !option.label.trim()) return null
      options.push({
        label: option.label.trim(),
        description: typeof option.description === 'string' && option.description.trim()
          ? option.description.trim()
          : null,
      })
    }
    if (!options.length) return null

    questions.push({
      question,
      options,
      multiSelect: data.multi_select === true,
    })
  }
  return questions
}

/** 回填给模型的结果：与原契约一致，只带题面与选中项。 */
export function askAnswersPayload(
  questions: AskQuestion[],
  selected: Record<number, string[]>,
): { answers: { question: string; selected: string[] }[] } {
  return {
    answers: questions.map((item, index) => ({
      question: item.question,
      selected: selected[index] ?? [],
    })),
  }
}
