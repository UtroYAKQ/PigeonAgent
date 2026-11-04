<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Check, ChevronLeft, ExternalLink, Loader2, Pencil, Plus, RefreshCw, Trash2, X } from '@lucide/vue'

import IconPicker from '@/components/admin/IconPicker.vue'
import LlmModelIcon from '@/components/chat/LlmModelIcon.vue'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { modelsApi } from '@/api/models'
import { errorMessage } from '@/lib/http'
import { MODEL_PROVIDERS, THINKING_LABELS, THINKING_LEVELS, THINKING_PRESETS } from '@/lib/modelOptions'
import { useChatStore } from '@/stores/chat'
import type {
  LlmModel,
  LlmModelCreatePayload,
  LlmModelUpdatePayload,
  ThinkingLevel,
} from '@/types/api'

interface ModelForm {
  name: string
  provider: string
  icon: string
  model_name: string
  base_url: string
  api_key: string
  context_window: string | number
  max_output_tokens: string | number
  compaction_threshold: string | number
  credit_input_per_1m: string | number
  credit_output_per_1m: string | number
  credit_cache_read_per_1m: string | number
  thinking_levels: ThinkingLevel[]
  supports_tools: boolean
  is_active: boolean
  is_default: boolean
}

// 管理台不属于对话域：模型列表直连 modelsApi，不借 chat store 的缓存
const chat = useChatStore()
const emit = defineEmits<{ 'scroll-top': [] }>()
const models = ref<LlmModel[]>([])
const mode = ref<'list' | 'form'>('list')
const editing = ref<LlmModel | null>(null)
const form = ref<ModelForm>(blankForm())
const saving = ref(false)
const pendingDeleteId = ref<number | null>(null)
const deleting = ref(false)
const formError = ref<string | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const nameInput = ref<InstanceType<typeof Input> | null>(null)
const thinkingDraft = ref('')

const THINKING_ALIASES: Record<string, ThinkingLevel> = {
  极低: 'minimal',
  低: 'low',
  中: 'medium',
  高: 'high',
  极高: 'xhigh',
  最高: 'max',
}

const THINKING_VALUES = new Set<string>(THINKING_LEVELS.map(level => level.value))

/**
 * 上面一组放真正会用到的供应商，冷门的才沉到「其他」。
 * 国内厂商排在前面：以前千问（alibaba）被塞在「其他」里，等于没有。
 */
const COMMON_PROVIDERS = [
  'alibaba',
  'deepseek',
  'moonshotai',
  'zai',
  'openai',
  'anthropic',
  'google',
  'google_cloud',
  'xai',
  'openrouter',
  'groq',
  'mistral',
  'azure',
  'bedrock',
  'vllm',
  'custom',
]
const PROVIDER_LABELS: Record<string, string> = {
  alibaba: '阿里云百炼 · 通义千问',
  moonshotai: '月之暗面 Kimi',
  zai: '智谱 GLM',
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  google: 'Google Gemini',
  google_cloud: 'Google Cloud Vertex',
  azure: 'Azure OpenAI',
  bedrock: 'AWS Bedrock',
  alibaba_cloud: '阿里云百炼 · 通义千问',
  xai: 'xAI Grok',
  openrouter: 'OpenRouter',
  groq: 'Groq',
  mistral: 'Mistral',
  cohere: 'Cohere',
  fireworks: 'Fireworks',
  together: 'Together',
  vllm: 'vLLM（自建）',
  custom: '自定义（OpenAI 兼容）',
}

const providerOptions = computed(() => {
  const values = new Set<string>(MODEL_PROVIDERS)
  const current = form.value.provider.trim()
  if (current) values.add(current)
  return {
    common: COMMON_PROVIDERS.filter(provider => values.has(provider)),
    others: [...values].filter(provider => !COMMON_PROVIDERS.includes(provider)),
  }
})

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider
}

const sortedModels = computed(() =>
  [...models.value].sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.id - b.id),
)

const thinkingPreset = computed(
  () => THINKING_PRESETS[form.value.provider.trim().toLowerCase()] ?? null,
)

const presetApplied = computed(() => {
  const preset = thinkingPreset.value
  if (!preset) return false
  return preset.levels.length === form.value.thinking_levels.length
    && preset.levels.every((level, index) => form.value.thinking_levels[index] === level)
})

function applyThinkingPreset(): void {
  if (!thinkingPreset.value) return
  form.value.thinking_levels = [...thinkingPreset.value.levels]
}

function blankForm(): ModelForm {
  return {
    name: '',
    provider: 'openai',
    icon: '',
    model_name: '',
    base_url: '',
    api_key: '',
    context_window: '',
    max_output_tokens: '',
    compaction_threshold: '',
    credit_input_per_1m: '',
    credit_output_per_1m: '',
    credit_cache_read_per_1m: '',
    thinking_levels: [],
    supports_tools: true,
    is_active: true,
    is_default: false,
  }
}

function resetList(): void {
  mode.value = 'list'
  editing.value = null
  formError.value = null
  pendingDeleteId.value = null
  emit('scroll-top')
}

function focusName(): void {
  emit('scroll-top')
  void nextTick().then(() => {
    // Input 组件的根节点就是这个原生 input，用模板 ref 拿它，不去 document 里抢
    const input = nameInput.value?.$el as HTMLInputElement | null
    if (!input) return
    input.focus()
    input.select()
  })
}

function startCreate(): void {
  editing.value = null
  form.value = blankForm()
  formError.value = null
  mode.value = 'form'
  focusName()
}

function startEdit(model: LlmModel): void {
  editing.value = model
  form.value = {
    name: model.name,
    provider: model.provider,
    icon: model.icon ?? '',
    model_name: model.model_name,
    base_url: model.base_url ?? '',
    api_key: '',
    context_window: model.context_window?.toString() ?? '',
    max_output_tokens: model.max_output_tokens?.toString() ?? '',
    compaction_threshold: model.compaction_threshold != null
      ? Math.round(model.compaction_threshold * 100).toString()
      : '',
    credit_input_per_1m: model.credit_input_per_1m?.toString() ?? '',
    credit_output_per_1m: model.credit_output_per_1m?.toString() ?? '',
    credit_cache_read_per_1m: model.credit_cache_read_per_1m?.toString() ?? '',
    thinking_levels: [...model.thinking_levels],
    supports_tools: model.supports_tools,
    is_active: model.is_active,
    is_default: model.is_default,
  }
  formError.value = null
  mode.value = 'form'
  focusName()
}

function levelLabel(value: ThinkingLevel): string {
  return THINKING_LABELS[value] ?? value
}

function levelLabels(levels: ThinkingLevel[]): string {
  return levels.map(levelLabel).join(' / ')
}

function addThinkingLevel(): void {
  const raw = thinkingDraft.value.trim()
  if (!raw) return
  const level = THINKING_ALIASES[raw.toLowerCase()] ?? (raw.toLowerCase() as ThinkingLevel)
  if (!THINKING_VALUES.has(level)) {
    toast.error('不支持的思考强度', {
      description: '可用值：minimal / low / medium / high / xhigh / max，也可以输入极低 / 低 / 中 / 高 / 极高 / 最高。',
    })
    return
  }
  if (form.value.thinking_levels.includes(level)) {
    thinkingDraft.value = ''
    return
  }
  if (form.value.thinking_levels.length >= THINKING_LEVELS.length) {
    toast.error('思考挡位数量已达上限')
    return
  }
  form.value.thinking_levels = [...form.value.thinking_levels, level]
  thinkingDraft.value = ''
}

function removeThinkingLevel(level: ThinkingLevel): void {
  form.value.thinking_levels = form.value.thinking_levels.filter(item => item !== level)
}

/**
 * 这三个输入框是 type="number"，Vue 的 v-model 会把值自动转成 number
 * （留空仍是 ''），所以这里不能假设拿到的一定是字符串。
 */
function parseOptionalPositive(value: string | number | null, label: string): number | null {
  const trimmed = String(value ?? '').trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label}必须是正整数`)
  }
  return parsed
}

function parseOptionalPercent(value: string | number | null, label: string): number | null {
  const trimmed = String(value ?? '').trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed) || parsed < 10 || parsed > 100) {
    throw new Error(`${label}必须在 10% 到 100% 之间`)
  }
  return parsed / 100
}

function parseOptionalNonNegative(value: string | number | null, label: string): number | null {
  const trimmed = String(value ?? '').trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${label}不能是负数`)
  }
  return parsed
}

async function refreshList(): Promise<void> {
  // 只有首次取数铺骨架屏；后续刷新保留旧列表，不让整块内容闪一下
  const initial = !models.value.length
  if (initial) loading.value = true
  loadError.value = null
  try {
    const data = await modelsApi.list()
    models.value = data.items
  } catch (error) {
    if (!models.value.length) loadError.value = errorMessage(error)
    else toast.error('模型列表刷新失败', { description: errorMessage(error) })
  } finally {
    loading.value = false
  }
}

/**
 * 改完配置后两边都要跟上：面板自己的列表，以及输入框依赖的对话 store 缓存。
 * 后者不属于本面板的数据源，只是让另一个域不至于继续展示已删掉的模型。
 */
async function syncAfterChange(): Promise<void> {
  await Promise.all([refreshList(), chat.refreshModels(), chat.refreshSessions().catch(() => undefined)])
}

/** 底部状态栏说当前真实状态，不复用标题文案占位 */
const formStatus = computed(() => {
  if (saving.value) return editing.value ? '正在保存修改…' : '正在添加模型…'
  if (editing.value) return `正在编辑「${editing.value.name}」`
  const name = form.value.name.trim()
  return name ? `将新增「${name}」` : '新模型，尚未保存'
})

async function save(): Promise<void> {
  if (saving.value) return
  formError.value = null
  const name = form.value.name.trim()
  const provider = form.value.provider.trim()
  const modelName = form.value.model_name.trim()
  if (!name || !provider || !modelName) {
    formError.value = '请填写展示名、供应商和模型 ID'
    return
  }

  let contextWindow: number | null
  let maxOutputTokens: number | null
  let compactionThreshold: number | null
  let creditInput: number | null
  let creditOutput: number | null
  let creditCacheRead: number | null
  try {
    contextWindow = parseOptionalPositive(form.value.context_window, '上下文窗口')
    maxOutputTokens = parseOptionalPositive(form.value.max_output_tokens, '最大输出')
    compactionThreshold = parseOptionalPercent(
      form.value.compaction_threshold,
      '上下文压缩阈值',
    )
    creditInput = parseOptionalNonNegative(form.value.credit_input_per_1m, '输入单价')
    creditOutput = parseOptionalNonNegative(form.value.credit_output_per_1m, '输出单价')
    creditCacheRead = parseOptionalNonNegative(
      form.value.credit_cache_read_per_1m,
      '缓存命中单价',
    )
  } catch (error) {
    formError.value = errorMessage(error)
    return
  }
  if (compactionThreshold != null && contextWindow == null) {
    formError.value = '填写上下文压缩阈值前，请先设置上下文窗口'
    return
  }

  const payload: LlmModelCreatePayload = {
    name,
    provider,
    icon: form.value.icon || null,
    model_name: modelName,
    base_url: form.value.base_url.trim() || null,
    context_window: contextWindow,
    max_output_tokens: maxOutputTokens,
    compaction_threshold: compactionThreshold,
    credit_input_per_1m: creditInput,
    credit_output_per_1m: creditOutput,
    credit_cache_read_per_1m: creditCacheRead,
    thinking_levels: form.value.thinking_levels,
    supports_tools: form.value.supports_tools,
    is_active: form.value.is_active,
    is_default: form.value.is_default,
  }
  const apiKey = form.value.api_key.trim()
  if (apiKey) payload.api_key = apiKey
  else if (!editing.value) payload.api_key = null

  saving.value = true
  try {
    if (editing.value) {
      await modelsApi.update(editing.value.id, payload as LlmModelUpdatePayload)
      toast.success('模型已更新')
    } else {
      await modelsApi.create(payload)
      toast.success('模型已添加')
    }
    await syncAfterChange()
    resetList()
  } catch (error) {
    formError.value = errorMessage(error)
  } finally {
    saving.value = false
  }
}

async function remove(model: LlmModel): Promise<void> {
  // 管理台约定：删除走两次点击确认，不弹 window.confirm 打断页面
  if (deleting.value) return
  if (pendingDeleteId.value !== model.id) {
    pendingDeleteId.value = model.id
    return
  }
  deleting.value = true
  try {
    await modelsApi.remove(model.id)
    pendingDeleteId.value = null
    if (editing.value?.id === model.id) resetList()
    await syncAfterChange()
    toast.success('模型已删除')
  } catch (error) {
    toast.error('删除模型失败', { description: errorMessage(error) })
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void refreshList()
})
</script>

<template>
  <div v-if="mode === 'list'" class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">
        共 {{ sortedModels.length }} 个模型 · 全局共享
      </p>
      <div class="flex items-center gap-2">
        <Button variant="outline" class="h-8" :disabled="loading" @click="refreshList">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
        <Button class="h-8" @click="startCreate">
          <Plus class="size-3.5" />
          新增模型
        </Button>
      </div>
    </div>

    <div v-if="loading" class="overflow-hidden rounded-lg border border-border bg-card">
      <div v-for="index in 3" :key="index" class="flex items-start gap-3 border-t border-border px-4 py-3 first:border-t-0">
        <div class="size-9 animate-pulse rounded-md bg-muted" />
        <div class="flex-1 space-y-2">
          <div class="h-3 w-32 animate-pulse rounded-full bg-muted" />
          <div class="h-3 w-1/2 animate-pulse rounded-full bg-muted" />
        </div>
      </div>
    </div>

    <div
      v-else-if="loadError"
      class="rounded-lg border border-border bg-card px-4 py-14 text-center"
    >
      <p class="text-sm font-medium">模型加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ loadError }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="refreshList">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <div
      v-else-if="!sortedModels.length"
      class="rounded-lg border border-border bg-card px-4 py-16 text-center"
    >
      <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
        <Plus class="size-4" />
      </span>
      <p class="mt-4 text-sm font-medium">还没有模型</p>
      <p class="mt-1 max-w-[320px] mx-auto text-sm leading-6 text-muted-foreground">
        添加一个模型后，就可以在输入框里选择它开始对话。
      </p>
      <Button class="mt-4 h-9" @click="startCreate">
        <Plus class="size-4" />
        新增模型
      </Button>
    </div>

    <div v-else class="overflow-hidden rounded-lg border border-border bg-card">
      <div
        v-for="model in sortedModels"
        :key="model.id"
        class="group/model flex items-start gap-3 border-t border-border px-4 py-3 transition-colors first:border-t-0 hover:bg-muted/40"
      >
        <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md border border-border bg-background">
          <LlmModelIcon :icon="model.icon" :name="model.name" :size="20" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="truncate text-[13px] font-medium">{{ model.name }}</p>
            <span
              v-if="model.is_default"
              class="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground"
            >
              默认
            </span>
            <span
              v-if="!model.is_active"
              class="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >
              已停用
            </span>
          </div>
          <p class="mt-1 truncate text-sm text-muted-foreground">
            {{ providerLabel(model.provider) }} · {{ model.model_name }}
          </p>
          <p v-if="model.thinking_levels.length" class="mt-1 text-xs text-muted-foreground">
            思考挡位：{{ levelLabels(model.thinking_levels) }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            上下文窗口：{{ model.context_window?.toLocaleString() ?? '未配置' }}
            <span v-if="model.compaction_threshold != null">
              · 达 {{ Math.round(model.compaction_threshold * 100) }}% 压缩
            </span>
          </p>
        </div>

        <div class="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            class="size-8 text-muted-foreground"
            aria-label="编辑模型"
            @click="startEdit(model)"
          >
            <Pencil class="size-4" />
          </Button>
          <template v-if="pendingDeleteId === model.id">
            <Button variant="destructive" size="sm" :disabled="deleting" @click="remove(model)">确认删除</Button>
            <Button variant="ghost" size="sm" class="text-muted-foreground" :disabled="deleting" @click="pendingDeleteId = null">取消</Button>
          </template>
          <Button
            v-else
            variant="ghost"
            size="icon-sm"
            class="size-8 text-muted-foreground hover:text-destructive"
            aria-label="删除模型"
            @click="remove(model)"
          >
            <Trash2 class="size-4" />
          </Button>
        </div>
      </div>
    </div>
  </div>

  <div v-else>
    <Button variant="ghost" class="-ml-2 mb-4 h-9 text-muted-foreground" @click="resetList">
      <ChevronLeft class="size-4" />
      返回模型列表
    </Button>

    <div class="mb-6">
      <h2 class="text-xl font-bold">{{ editing ? '编辑模型' : '新增模型' }}</h2>
      <p class="mt-1 text-sm leading-6 text-muted-foreground">
        模型全局共享，保存后所有成员都可以在输入框里选择。
      </p>
    </div>

    <form id="model-form" class="space-y-8" @submit.prevent="save">
      <ConsoleSection title="基础信息">
        <div class="space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="grid gap-2">
              <span class="text-sm font-medium">展示名</span>
              <Input
                ref="nameInput"
                v-model="form.name"
                required
                maxlength="64"
                placeholder="例如 GPT-5"
                class="h-9 text-sm"
              />
            </label>
            <label class="grid gap-2">
              <span class="text-sm font-medium">供应商</span>
              <Select v-model="form.provider">
                <SelectTrigger class="h-9 w-full text-sm">
                  <SelectValue placeholder="选择供应商" />
                </SelectTrigger>
                <SelectContent
                  position="popper"
                  class="max-h-[300px] w-[var(--reka-select-trigger-width)]"
                >
                  <SelectGroup>
                    <SelectLabel class="px-2 py-1.5 text-[11px] text-muted-foreground">常用</SelectLabel>
                    <SelectItem
                      v-for="provider in providerOptions.common"
                      :key="provider"
                      :value="provider"
                      class="text-[13px]"
                    >
                      {{ providerLabel(provider) }}
                    </SelectItem>
                  </SelectGroup>
                  <SelectGroup v-if="providerOptions.others.length">
                    <SelectLabel class="px-2 py-1.5 text-[11px] text-muted-foreground">其他</SelectLabel>
                    <SelectItem
                      v-for="provider in providerOptions.others"
                      :key="provider"
                      :value="provider"
                      class="text-[13px]"
                    >
                      {{ providerLabel(provider) }}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </label>
          </div>

          <label class="grid gap-2">
            <span class="text-sm font-medium">模型 ID</span>
            <Input
              v-model="form.model_name"
              required
              maxlength="128"
              placeholder="供应商侧的模型名"
              class="h-9 font-mono text-sm"
            />
          </label>

          <IconPicker v-model="form.icon" />
        </div>
      </ConsoleSection>

      <ConsoleSection title="连接与参数">
        <div class="space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="grid gap-2">
              <span class="text-sm font-medium">API 地址</span>
              <Input
                v-model="form.base_url"
                maxlength="512"
                placeholder="可选，自定义网关"
                class="h-9 text-sm"
              />
            </label>
            <label class="grid gap-2">
              <span class="text-sm font-medium">API Key</span>
              <Input
                v-model="form.api_key"
                type="password"
                autocomplete="new-password"
                :placeholder="editing ? '留空则不修改' : '可选'"
                class="h-9 font-mono text-sm"
              />
            </label>
          </div>

          <div class="grid gap-4 sm:grid-cols-2">
            <label class="grid gap-2">
              <span class="text-sm font-medium">上下文窗口</span>
              <Input
                v-model="form.context_window"
                type="number"
                min="1"
                placeholder="tokens，可选"
                class="h-9 text-sm"
              />
              <span class="text-xs leading-5 text-muted-foreground">
                按模型实际能力填写，例如 Qwen3.8-flash 这类 1M 模型填 1000000。
              </span>
            </label>
            <label class="grid gap-2">
              <span class="text-sm font-medium">最大输出</span>
              <Input
                v-model="form.max_output_tokens"
                type="number"
                min="1"
                placeholder="tokens，可选"
                class="h-9 text-sm"
              />
              <span class="text-xs leading-5 text-muted-foreground">
                建议 32768，最低不要低于 16384；再低时 HTML、代码和工具参数容易被截断。最终上限以服务商为准。
              </span>
            </label>
          </div>

          <label class="grid gap-2">
            <span class="text-sm font-medium">上下文压缩阈值 (%)</span>
            <Input
              v-model="form.compaction_threshold"
              type="number"
              min="10"
              max="100"
              step="1"
              placeholder="留空使用全局默认 80"
              class="h-9 text-sm"
            />
            <span class="text-xs leading-5 text-muted-foreground">
              估算上下文达到上下文窗口的该比例时自动压缩历史；需要先填写上下文窗口。
            </span>
          </label>

          <div class="grid gap-4 sm:grid-cols-3">
            <label class="grid gap-2">
              <span class="text-sm font-medium">输入积分单价</span>
              <Input
                v-model="form.credit_input_per_1m"
                type="number"
                min="0"
                step="0.1"
                placeholder="积分 / 1M token，可选"
                class="h-9 text-sm"
              />
            </label>
            <label class="grid gap-2">
              <span class="text-sm font-medium">输出积分单价</span>
              <Input
                v-model="form.credit_output_per_1m"
                type="number"
                min="0"
                step="0.1"
                placeholder="积分 / 1M token，可选"
                class="h-9 text-sm"
              />
            </label>
            <label class="grid gap-2">
              <span class="text-sm font-medium">缓存命中单价</span>
              <Input
                v-model="form.credit_cache_read_per_1m"
                type="number"
                min="0"
                step="0.1"
                placeholder="积分 / 1M token，可选"
                class="h-9 text-sm"
              />
            </label>
            <span class="text-xs leading-5 text-muted-foreground sm:col-span-3">
              计费开启时按实际用量折算：缓存命中已包含在输入 token 里，命中部分按缓存价、其余按输入价；缓存命中单价留空时按输入单价（即不打折），输入/输出单价留空时使用全局默认。
            </span>
          </div>
        </div>
      </ConsoleSection>

      <ConsoleSection title="能力">
        <div class="space-y-4">
          <div>
            <p class="text-sm font-medium">思考挡位</p>
            <p class="mt-1 text-sm leading-6 text-muted-foreground">
              按模型逐个添加；可输入 minimal / low / medium / high / xhigh / max 或中文名。不添加则输入框不显示挡位选择。
            </p>
          </div>

          <div
            v-if="thinkingPreset"
            class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-muted/40 px-3 py-2.5 text-xs leading-5 text-muted-foreground"
          >
            <span>官方预设</span>
            <span class="text-foreground">{{ thinkingPreset.levels.map(levelLabel).join(' / ') }}</span>
            <button
              type="button"
              class="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-4 transition-opacity hover:opacity-75 disabled:opacity-50"
              :disabled="presetApplied"
              @click="applyThinkingPreset"
            >
              <Check v-if="presetApplied" class="size-3" :stroke-width="2.2" />
              {{ presetApplied ? '已应用' : '应用' }}
            </button>
            <a
              :href="thinkingPreset.url"
              target="_blank"
              rel="noreferrer"
              class="ml-auto inline-flex items-center gap-0.5 text-muted-foreground transition-colors hover:text-foreground"
              :title="thinkingPreset.label"
            >
              官方说明
              <ExternalLink class="size-3" />
            </a>
          </div>

          <div v-if="form.thinking_levels.length" class="flex flex-wrap gap-2">
            <span
              v-for="level in form.thinking_levels"
              :key="level"
              class="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-muted px-2 text-xs text-foreground"
            >
              {{ levelLabel(level) }}
              <span class="font-mono text-[10px] text-muted-foreground">{{ level }}</span>
              <button
                type="button"
                class="grid size-5 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                :aria-label="`移除 ${levelLabel(level)}`"
                @click="removeThinkingLevel(level)"
              >
                <X class="size-3" />
              </button>
            </span>
          </div>
          <p v-else class="text-sm text-muted-foreground">还没有添加挡位</p>

          <div class="flex gap-2">
            <Input
              v-model="thinkingDraft"
              placeholder="输入挡位，例如 high"
              class="h-9 min-w-0 flex-1 text-sm"
              @keydown.enter.prevent="addThinkingLevel"
            />
            <Button type="button" variant="outline" class="h-9 shrink-0" @click="addThinkingLevel">
              <Plus class="size-4" />
              添加
            </Button>
          </div>

          <div class="space-y-3 border-t border-border pt-4">
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="text-sm font-medium">支持工具调用</p>
                <p class="mt-1 text-xs text-muted-foreground">关闭后不向该模型下发工具</p>
              </div>
              <Switch v-model="form.supports_tools" aria-label="支持工具调用" />
            </div>
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="text-sm font-medium">启用</p>
                <p class="mt-1 text-xs text-muted-foreground">停用后不会出现在可选列表</p>
              </div>
              <Switch v-model="form.is_active" aria-label="启用模型" />
            </div>
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="text-sm font-medium">设为默认</p>
                <p class="mt-1 text-xs text-muted-foreground">新对话优先使用</p>
              </div>
              <Switch v-model="form.is_default" aria-label="设为默认模型" />
            </div>
          </div>
        </div>
      </ConsoleSection>

      <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-background px-4 py-2.5">
        <p
          class="min-w-0 flex-1 text-sm leading-6"
          :class="formError ? 'text-destructive' : 'text-muted-foreground'"
        >
          {{ formError || formStatus }}
        </p>
        <div class="flex shrink-0 items-center gap-2">
          <Button type="button" variant="ghost" class="h-9 text-muted-foreground" @click="resetList">
            取消
          </Button>
          <Button type="submit" form="model-form" class="h-9" :disabled="saving">
            <Loader2 v-if="saving" class="size-4 animate-spin" />
            {{ editing ? '保存' : '添加模型' }}
          </Button>
        </div>
      </div>
    </form>
  </div>
</template>
