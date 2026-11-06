<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { ChevronLeft, Image, Loader2, Pencil, Plus, RefreshCw, Trash2 } from '@lucide/vue'

import IconPicker from '@/components/admin/IconPicker.vue'
import LlmModelIcon from '@/components/chat/LlmModelIcon.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { imageModelsApi } from '@/api/imageModels'
import { errorMessage } from '@/lib/http'
import type {
  ImageModel,
  ImageModelCreatePayload,
  ImageModelUpdatePayload,
  ImageProviderPreset,
} from '@/types/api'

interface ImageModelForm {
  name: string
  icon: string
  provider: string
  protocol: string
  model_name: string
  base_url: string
  api_key: string
  sizes: string
  default_size: string
  // type="number" 的输入框由 Vue 自动转成 number，留空才是 ''
  max_images: string | number
  quality: string
  credit_per_image: string | number
  is_active: boolean
  is_default: boolean
}

const DEFAULT_SIZES = '1024x1024, 1536x1024, 1024x1536'
// 与后端 ImageModelBase 对齐：尺寸档最多 8 个，且只接受 WxH
const MAX_SIZE_TIERS = 8
const SIZE_TIER_PATTERN = /^\d{2,5}x\d{2,5}$/

/**
 * 协议是供应商的属性而不是自由选项——选错了接口直接 404，所以只有自定义网关才让选。
 * 清单只留一份：下拉选项和预设芯片的标签都从这里取，取值与后端 ImageProtocol 枚举一致；
 * note 只在展开的下拉里出现，芯片上的标签要保持短。
 */
const PROTOCOL_OPTIONS: { value: string; label: string; note?: string }[] = [
  { value: 'openai', label: 'OpenAI 兼容', note: '/images/generations' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'bedrock', label: 'AWS Bedrock' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'fal_ai', label: 'fal.ai' },
  { value: 'stability', label: 'Stability AI' },
  { value: 'vertex_ai', label: 'Vertex AI' },
  { value: 'openrouter', label: 'OpenRouter' },
]

function protocolLabel(protocol: string): string {
  return PROTOCOL_OPTIONS.find(option => option.value === protocol)?.label ?? protocol
}

const emit = defineEmits<{ 'scroll-top': [] }>()
const models = ref<ImageModel[]>([])
const providers = ref<ImageProviderPreset[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const mode = ref<'list' | 'form'>('list')
const editing = ref<ImageModel | null>(null)
const form = ref<ImageModelForm>(blankForm())
const saving = ref(false)
const formError = ref<string | null>(null)
const pendingDeleteId = ref<number | null>(null)
const deleting = ref(false)

const sortedModels = computed(() =>
  [...models.value].sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.id - b.id),
)

const parsedSizes = computed(() =>
  form.value.sizes.split(/[,\s]+/).map(item => item.trim()).filter(Boolean),
)

const activeProvider = computed(
  () => providers.value.find(item => item.key === form.value.provider) ?? null,
)

/** 预览最终请求地址：拼接规则要和后端 resolve_base_url + preset.path 保持一致 */
const endpointPreview = computed(() => {
  const preset = activeProvider.value
  if (!preset) return ''
  const root = (form.value.base_url.trim() || preset.base_url || '').replace(/\/+$/, '')
  if (!root) return ''
  return root.endsWith(preset.path) ? root : `${root}${preset.path}`
})

const sizeOptions = computed(() => {
  const values = [...parsedSizes.value]
  if (form.value.default_size && !values.includes(form.value.default_size)) {
    values.push(form.value.default_size)
  }
  return values
})

function blankForm(): ImageModelForm {
  return {
    name: '',
    icon: '',
    provider: 'openai',
    protocol: 'openai',
    model_name: '',
    base_url: '',
    api_key: '',
    sizes: DEFAULT_SIZES,
    default_size: '1024x1024',
    max_images: '4',
    quality: '',
    credit_per_image: '',
    is_active: true,
    is_default: false,
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const [data, presetList] = await Promise.all([
      imageModelsApi.list(),
      imageModelsApi.listProviders(),
    ])
    models.value = data.items
    providers.value = presetList
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function applyProvider(key: string): void {
  // 再次选中同一项不该把用户手改过的地址重置回预设
  if (key === form.value.provider && form.value.base_url) return
  form.value.provider = key
  const preset = providers.value.find(item => item.key === key)
  if (!preset) return
  // 地址、协议和尺寸跟着供应商走，用户只需要补 model 和 key
  form.value.base_url = preset.base_url ?? ''
  form.value.protocol = preset.protocol
  if (preset.sizes.length) {
    form.value.sizes = preset.sizes.join(', ')
    form.value.default_size = preset.sizes[0]
  }
}

/** 自定义网关要自己声明协议；预设供应商的协议由预设决定 */
const usingCustomAddress = computed(
  () => Boolean(form.value.base_url) && form.value.base_url !== (activeProvider.value?.base_url ?? ''),
)

function startCreate(): void {
  editing.value = null
  form.value = blankForm()
  formError.value = null
  mode.value = 'form'
  emit('scroll-top')
}

function startEdit(model: ImageModel): void {
  editing.value = model
  form.value = {
    name: model.name,
    icon: model.icon ?? '',
    provider: model.provider,
    protocol: model.protocol,
    model_name: model.model_name,
    base_url: model.base_url ?? '',
    api_key: '',
    sizes: model.sizes.join(', '),
    default_size: model.default_size,
    max_images: String(model.max_images),
    quality: model.quality ?? '',
    credit_per_image: model.credit_per_image?.toString() ?? '',
    is_active: model.is_active,
    is_default: model.is_default,
  }
  formError.value = null
  mode.value = 'form'
  emit('scroll-top')
}

function resetList(): void {
  mode.value = 'list'
  editing.value = null
  formError.value = null
  pendingDeleteId.value = null
  emit('scroll-top')
}

async function save(): Promise<void> {
  if (saving.value) return
  formError.value = null
  const name = form.value.name.trim()
  const modelName = form.value.model_name.trim()
  const sizes = parsedSizes.value
  if (!name) return void (formError.value = '请填写展示名称')
  if (!modelName) return void (formError.value = '请填写上游模型名')
  if (!sizes.length) return void (formError.value = '至少填一个尺寸档')
  if (sizes.length > MAX_SIZE_TIERS) {
    return void (formError.value = `尺寸档最多 ${MAX_SIZE_TIERS} 个`)
  }
  const malformed = sizes.find(size => !SIZE_TIER_PATTERN.test(size))
  if (malformed) {
    return void (formError.value = `尺寸档要写成 宽x高，例如 1024x1024（「${malformed}」不合规）`)
  }
  if (!sizes.includes(form.value.default_size)) {
    return void (formError.value = '默认尺寸必须在尺寸档里')
  }
  const maxImages = Number(form.value.max_images)
  if (!Number.isInteger(maxImages) || maxImages < 1 || maxImages > 8) {
    return void (formError.value = '单次最多生成张数需在 1 到 8 之间')
  }
  const perImageRaw = String(form.value.credit_per_image ?? '').trim()
  let perImage: number | null = null
  if (perImageRaw) {
    perImage = Number(perImageRaw)
    if (!Number.isFinite(perImage) || perImage < 0) {
      return void (formError.value = '每张积分单价不能是负数')
    }
  }

  const payload: ImageModelCreatePayload = {
    name,
    provider: form.value.provider,
    protocol: form.value.protocol,
    icon: form.value.icon || null,
    model_name: modelName,
    base_url: form.value.base_url.trim() || null,
    sizes,
    default_size: form.value.default_size,
    max_images: maxImages,
    quality: form.value.quality.trim() || null,
    credit_per_image: perImage,
    is_active: form.value.is_active,
    is_default: form.value.is_default,
  }
  const apiKey = form.value.api_key.trim()

  saving.value = true
  try {
    if (editing.value) {
      const patch: ImageModelUpdatePayload = { ...payload }
      // 留空表示不改密钥
      if (apiKey) patch.api_key = apiKey
      await imageModelsApi.update(editing.value.id, patch)
      toast.success('图片模型已更新')
    } else {
      if (apiKey) payload.api_key = apiKey
      await imageModelsApi.create(payload)
      toast.success('图片模型已添加')
    }
    await load()
    resetList()
  } catch (error) {
    formError.value = errorMessage(error)
  } finally {
    saving.value = false
  }
}

async function remove(model: ImageModel): Promise<void> {
  // 管理台约定：删除走两次点击确认，不弹 window.confirm 打断页面
  if (deleting.value) return
  if (pendingDeleteId.value !== model.id) {
    pendingDeleteId.value = model.id
    return
  }
  deleting.value = true
  try {
    await imageModelsApi.remove(model.id)
    pendingDeleteId.value = null
    if (editing.value?.id === model.id) resetList()
    await load()
    toast.success('图片模型已删除')
  } catch (error) {
    toast.error('删除图片模型失败', { description: errorMessage(error) })
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="mode === 'list'" class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">
        共 {{ sortedModels.length }} 个图片模型 · 全局共享
      </p>
      <div class="flex items-center gap-2">
        <Button variant="outline" class="h-8" :disabled="loading" @click="load">
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
      <div v-for="index in 3" :key="index" class="flex items-center gap-3 border-t border-border px-4 py-3 first:border-t-0">
        <div class="size-9 animate-pulse rounded-md bg-muted" />
        <div class="flex-1 space-y-2">
          <div class="h-3 w-32 animate-pulse rounded-full bg-muted" />
          <div class="h-3 w-1/2 animate-pulse rounded-full bg-muted" />
        </div>
      </div>
    </div>

    <div v-else-if="loadError" class="rounded-lg border border-border bg-card px-4 py-14 text-center">
      <p class="text-sm font-medium">图片模型加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ loadError }}</p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <div v-else-if="!sortedModels.length" class="rounded-lg border border-dashed border-border px-4 py-14 text-center">
      <Image class="mx-auto size-8 text-muted-foreground/60" />
      <p class="mt-3 text-sm font-medium">还没有图片模型</p>
      <p class="mx-auto mt-1 max-w-[420px] text-sm leading-6 text-muted-foreground">
        添加一个 OpenAI Images 兼容的模型后，助手就能在对话里直接生成图片。
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
            >默认</span>
            <span
              v-if="!model.is_active"
              class="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >已停用</span>
          </div>
          <p class="mt-1 truncate text-sm text-muted-foreground">
            {{ model.model_name }}
            <span v-if="model.base_url"> · {{ model.base_url }}</span>
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            {{ model.sizes.join(' / ') }} · 默认 {{ model.default_size }} · 单次最多 {{ model.max_images }} 张
            <span v-if="model.quality"> · {{ model.quality }}</span>
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            class="size-8 text-muted-foreground"
            aria-label="编辑图片模型"
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
            aria-label="删除图片模型"
            @click="remove(model)"
          >
            <Trash2 class="size-4" />
          </Button>
        </div>
      </div>
    </div>
  </div>

  <div v-else class="space-y-5">
    <div class="flex items-center gap-2">
      <Button variant="ghost" class="h-8 px-2" @click="resetList">
        <ChevronLeft class="size-4" />
        返回
      </Button>
      <p class="text-sm font-medium">{{ editing ? '编辑图片模型' : '新增图片模型' }}</p>
    </div>

    <div class="space-y-4 rounded-lg border border-border bg-card p-4">
      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">供应商</span>
        <Select :model-value="form.provider" @update:model-value="applyProvider(String($event))">
          <SelectTrigger class="h-9">
            <SelectValue placeholder="选择供应商" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="preset in providers" :key="preset.key" :value="preset.key">
              {{ preset.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span
          v-if="activeProvider && form.provider !== 'custom'"
          class="flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground"
        >
          <span class="rounded border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[10.5px]">
            {{ protocolLabel(activeProvider.protocol) }}
          </span>
          <span class="font-mono text-[10.5px]">{{ activeProvider.path }}</span>
        </span>
        <span v-if="activeProvider?.note" class="block text-[11.5px] text-muted-foreground">
          {{ activeProvider.note }}
        </span>
      </label>

      <label v-if="form.provider === 'custom'" class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">协议</span>
        <Select v-model="form.protocol">
          <SelectTrigger class="h-9">
            <SelectValue placeholder="选择协议" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="option in PROTOCOL_OPTIONS" :key="option.value" :value="option.value">
              {{ option.note ? `${option.label}（${option.note}）` : option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="block text-[11.5px] leading-5 text-muted-foreground">
          {{ '决定 LiteLLM 用哪套请求形状打这个网关。除 OpenAI 兼容外，其余协议还需要各自的专属参数（api-version、区域、签名），当前版本只透传地址。' }}
        </span>
      </label>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">展示名称</span>
          <Input v-model="form.name" maxlength="64" placeholder="例如 Seedream 4.0" />
        </label>
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">上游模型名</span>
          <Input
            v-model="form.model_name"
            maxlength="128"
            :placeholder="activeProvider ? `例如 ${activeProvider.model_hint}` : '例如 gpt-image-1'"
          />
        </label>
      </div>

      <IconPicker v-model="form.icon" />

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">接口地址</span>
        <Input
          v-model="form.base_url"
          maxlength="512"
          :placeholder="activeProvider?.base_url ?? 'https://gateway.example.com/v1'"
        />
        <span class="block text-[11.5px] leading-5 text-muted-foreground">
          实际请求：<code class="font-mono text-foreground/80">{{ endpointPreview || '—' }}</code>
          <br>
          填到版本前缀即可（如 /v1、/api/v3），路径由供应商决定；也可直接粘贴完整地址。
          <span v-if="usingCustomAddress" class="text-foreground/70">
            当前使用的是自定义地址，与预设不同。
          </span>
        </span>
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">API Key</span>
        <Input
          v-model="form.api_key"
          type="password"
          :placeholder="editing ? '留空表示不修改' : 'sk-...'"
        />
      </label>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">尺寸档</span>
          <Input v-model="form.sizes" placeholder="1024x1024, 1536x1024" />
          <span class="block text-[11.5px] text-muted-foreground">宽x高，逗号分隔，最多 {{ MAX_SIZE_TIERS }} 档</span>
        </label>
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">默认尺寸</span>
          <Select v-model="form.default_size">
            <SelectTrigger class="h-9">
              <SelectValue placeholder="选择默认尺寸" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="size in sizeOptions" :key="size" :value="size">{{ size }}</SelectItem>
            </SelectContent>
          </Select>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">单次最多张数</span>
          <Input v-model="form.max_images" type="number" min="1" max="8" />
        </label>
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">画质档（可选）</span>
          <Input v-model="form.quality" maxlength="32" placeholder="hd / standard，留空不传" />
        </label>
        <label class="space-y-1.5">
          <span class="text-[12.5px] font-medium">每张积分单价</span>
          <Input
            v-model="form.credit_per_image"
            type="number"
            min="0"
            step="0.1"
            placeholder="积分 / 张，可选"
          />
          <span class="block text-[11.5px] leading-5 text-muted-foreground">
            计费开启时按出图张数扣分；留空使用后台「积分」里的默认单价。
          </span>
        </label>
      </div>

      <div class="flex flex-wrap items-center gap-6 pt-1">
        <label class="flex items-center gap-2 text-[13px]">
          <Switch v-model="form.is_active" />
          启用
        </label>
        <label class="flex items-center gap-2 text-[13px]">
          <Switch v-model="form.is_default" />
          设为默认
        </label>
      </div>

      <p v-if="formError" class="text-[12.5px] text-destructive">{{ formError }}</p>

      <div class="flex items-center justify-end gap-2 pt-1">
        <Button variant="outline" class="h-9" @click="resetList">取消</Button>
        <Button class="h-9" :disabled="saving" @click="save">
          <Loader2 v-if="saving" class="size-3.5 animate-spin" />
          保存
        </Button>
      </div>
    </div>
  </div>
</template>
