import type { ThinkingLevel } from '@/types/api'

export const THINKING_LEVELS: Array<{ value: ThinkingLevel; label: string; hint: string }> = [
  { value: 'minimal', label: '极低', hint: '几乎不思考，响应最快' },
  { value: 'low', label: '低', hint: '少量推理' },
  { value: 'medium', label: '中', hint: '平衡速度与深度' },
  { value: 'high', label: '高', hint: '更充分的推理' },
  { value: 'xhigh', label: '极高', hint: '复杂任务，耗时更长' },
  { value: 'max', label: '最高', hint: '尽可能深入' },
]

export const THINKING_LABELS: Record<ThinkingLevel, string> = Object.fromEntries(
  THINKING_LEVELS.map(item => [item.value, item.label]),
) as Record<ThinkingLevel, string>

export interface ThinkingPreset {
  levels: ThinkingLevel[]
  label: string
  url: string
}

// 只收录官方文档明确列出思考强度的厂商；没有官方说明就留给管理员手动添加。
export const THINKING_PRESETS: Record<string, ThinkingPreset> = {
  openai: {
    levels: ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
    label: 'OpenAI reasoning effort',
    url: 'https://developers.openai.com/api/docs/guides/reasoning',
  },
  google: {
    levels: ['minimal', 'low', 'medium', 'high'],
    label: 'Gemini thinking level',
    url: 'https://ai.google.dev/gemini-api/docs/thinking',
  },
  google_cloud: {
    levels: ['minimal', 'low', 'medium', 'high'],
    label: 'Gemini thinking level',
    url: 'https://ai.google.dev/gemini-api/docs/thinking',
  },
  deepseek: {
    levels: ['low', 'high', 'max'],
    label: 'DeepSeek 思考强度',
    url: 'https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/',
  },
  xai: {
    levels: ['low', 'medium', 'high', 'xhigh'],
    label: 'xAI reasoning effort',
    url: 'https://docs.x.ai/developers/model-capabilities/text/reasoning',
  },
  openrouter: {
    levels: ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
    label: 'OpenRouter reasoning effort',
    url: 'https://openrouter.ai/docs/guides/best-practices/reasoning-tokens',
  },
}

export const MODEL_PROVIDERS = [
  'openai',
  'anthropic',
  'google',
  'google_cloud',
  'deepseek',
  'azure',
  'bedrock',
  'alibaba',
  'moonshotai',
  'zai',
  'xai',
  'openrouter',
  'groq',
  'mistral',
  'cohere',
  'fireworks',
  'together',
  'vllm',
  'custom',
] as const
