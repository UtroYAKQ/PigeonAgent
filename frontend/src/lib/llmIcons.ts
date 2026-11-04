const modules = import.meta.glob<string>('../assets/llm-icons/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
})

export interface LlmIcon {
  key: string
  label: string
  url: string
  mono: boolean
}

const LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  claude: 'Claude',
  gemini: 'Gemini',
  google: 'Google',
  vertexai: 'Vertex AI',
  deepseek: 'DeepSeek',
  qwen: 'Qwen',
  alibaba: '阿里云',
  moonshot: 'Moonshot',
  kimi: 'Kimi',
  zhipu: '智谱',
  glm: 'GLM',
  groq: 'Groq',
  xai: 'xAI',
  grok: 'Grok',
  mistral: 'Mistral',
  meta: 'Meta',
  openrouter: 'OpenRouter',
  ollama: 'Ollama',
  azure: 'Azure',
  cohere: 'Cohere',
  perplexity: 'Perplexity',
  doubao: '豆包',
  bytedance: 'ByteDance',
  hunyuan: '混元',
  tencent: '腾讯云',
  baidu: '百度',
  minimax: 'MiniMax',
  yi: '零一万物',
  baichuan: '百川',
  stepfun: '阶跃星辰',
  siliconcloud: 'SiliconCloud',
  together: 'Together',
  fireworks: 'Fireworks',
  cerebras: 'Cerebras',
  nvidia: 'NVIDIA',
  bedrock: 'Bedrock',
  copilot: 'Copilot',
  lmstudio: 'LM Studio',
  vllm: 'vLLM',
  modelscope: 'ModelScope',
  github: 'GitHub',
}

// 单色图标跟随前景色，深色模式下需要反相
const MONO = new Set([
  'openai',
  'anthropic',
  'moonshot',
  'groq',
  'xai',
  'grok',
  'ollama',
  'lmstudio',
  'github',
])

const ORDER = [
  'openai', 'anthropic', 'claude', 'gemini', 'google', 'vertexai',
  'deepseek', 'qwen', 'alibaba', 'moonshot', 'kimi', 'zhipu', 'glm',
  'doubao', 'bytedance', 'hunyuan', 'tencent', 'baidu', 'minimax', 'yi',
  'baichuan', 'stepfun', 'siliconcloud', 'groq', 'xai', 'grok',
  'mistral', 'meta', 'openrouter', 'ollama', 'lmstudio', 'vllm',
  'azure', 'bedrock', 'cohere', 'perplexity', 'together', 'fireworks',
  'cerebras', 'nvidia', 'copilot', 'modelscope', 'github',
]

const byKey = new Map<string, LlmIcon>()
for (const [path, url] of Object.entries(modules)) {
  const key = path.split('/').pop()?.replace('.svg', '') ?? ''
  if (!key) continue
  byKey.set(key, {
    key,
    label: LABELS[key] ?? key,
    url,
    mono: MONO.has(key),
  })
}

export const LLM_ICONS: LlmIcon[] = ORDER
  .map(key => byKey.get(key))
  .filter((icon): icon is LlmIcon => Boolean(icon))

export function findLlmIcon(key: string | null | undefined): LlmIcon | null {
  if (!key) return null
  return byKey.get(key) ?? null
}
