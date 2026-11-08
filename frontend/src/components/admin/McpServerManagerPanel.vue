<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import {
  ChevronLeft,
  Loader2,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  Trash2,
} from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { mcpServersApi } from '@/api/mcpServers'
import { errorMessage } from '@/lib/http'
import type {
  AdminMcpServer,
  AdminMcpServerCreatePayload,
  McpServerTestResult,
} from '@/types/api'

interface McpServerForm {
  name: string
  slug: string
  url: string
  description: string
  auth: string
  clear_auth: boolean
  timeout_seconds: string | number
  enabled: boolean
  requires_approval: boolean
  defer_loading: boolean
}

type McpServerFormPayload = Omit<AdminMcpServerCreatePayload, 'auth'> & {
  auth?: string | null
}

const emit = defineEmits<{ 'scroll-top': [] }>()
const servers = ref<AdminMcpServer[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const mode = ref<'list' | 'form'>('list')
const editing = ref<AdminMcpServer | null>(null)
const form = ref<McpServerForm>(blankForm())
const saving = ref(false)
const formError = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const deleting = ref(false)
const testingId = ref<string | null>(null)
const testResult = ref<McpServerTestResult | null>(null)

function blankForm(): McpServerForm {
  return {
    name: '',
    slug: '',
    url: '',
    description: '',
    auth: '',
    clear_auth: false,
    timeout_seconds: '120',
    enabled: true,
    requires_approval: true,
    defer_loading: true,
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    servers.value = (await mcpServersApi.list()).items
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function startCreate(): void {
  editing.value = null
  form.value = blankForm()
  formError.value = null
  testResult.value = null
  mode.value = 'form'
  emit('scroll-top')
}

function startEdit(server: AdminMcpServer): void {
  editing.value = server
  form.value = {
    name: server.name,
    slug: server.slug,
    url: server.url,
    description: server.description ?? '',
    auth: '',
    clear_auth: false,
    timeout_seconds: String(server.timeout_seconds),
    enabled: server.enabled,
    requires_approval: server.requires_approval,
    defer_loading: server.defer_loading,
  }
  formError.value = null
  testResult.value = null
  mode.value = 'form'
  emit('scroll-top')
}

function resetList(): void {
  mode.value = 'list'
  editing.value = null
  formError.value = null
  testResult.value = null
  pendingDeleteId.value = null
  emit('scroll-top')
}

function payload(): McpServerFormPayload | null {
  const name = form.value.name.trim()
  const slug = form.value.slug.trim().toLowerCase()
  const url = form.value.url.trim()
  const timeout = Number(form.value.timeout_seconds)
  if (!name) {
    formError.value = '请填写服务器名称'
    return null
  }
  if (!/^[a-z0-9_]{2,32}$/.test(slug)) {
    formError.value = 'slug 只能包含小写字母、数字和下划线，长度 2~32'
    return null
  }
  if (!/^https?:\/\/\S+$/i.test(url)) {
    formError.value = '请填写 http/https 地址'
    return null
  }
  if (!Number.isInteger(timeout) || timeout < 10 || timeout > 600) {
    formError.value = '超时需在 10 到 600 秒之间'
    return null
  }
  const result: McpServerFormPayload = {
    name,
    slug,
    url,
    description: form.value.description.trim() || null,
    timeout_seconds: timeout,
    enabled: form.value.enabled,
    requires_approval: form.value.requires_approval,
    defer_loading: form.value.defer_loading,
  }
  if (form.value.clear_auth && editing.value?.has_auth) {
    result.auth = null
  } else {
    const auth = form.value.auth.trim()
    if (auth) result.auth = auth
  }
  return result
}

async function save(): Promise<void> {
  if (saving.value) return
  formError.value = null
  const body = payload()
  if (!body) return
  saving.value = true
  try {
    if (editing.value) {
      await mcpServersApi.update(editing.value.id, body)
      toast.success('MCP 服务器已更新')
    } else {
      const { auth, ...rest } = body
      await mcpServersApi.create({ ...rest, ...(typeof auth === 'string' ? { auth } : {}) })
      toast.success('MCP 服务器已添加')
    }
    await load()
    resetList()
  } catch (error) {
    formError.value = errorMessage(error)
  } finally {
    saving.value = false
  }
}

async function remove(server: AdminMcpServer): Promise<void> {
  if (deleting.value) return
  if (pendingDeleteId.value !== server.id) {
    pendingDeleteId.value = server.id
    return
  }
  deleting.value = true
  try {
    await mcpServersApi.remove(server.id)
    pendingDeleteId.value = null
    if (editing.value?.id === server.id) resetList()
    await load()
    toast.success('MCP 服务器已删除')
  } catch (error) {
    toast.error('删除 MCP 服务器失败', { description: errorMessage(error) })
  } finally {
    deleting.value = false
  }
}

async function test(server: AdminMcpServer): Promise<void> {
  if (testingId.value) return
  testingId.value = server.id
  testResult.value = null
  try {
    const result = await mcpServersApi.test(server.id)
    testResult.value = result
    if (result.ok) {
      toast.success(`连接成功，发现 ${result.tools.length} 个工具`)
      await load()
    } else {
      toast.error('连接失败', { description: result.error ?? '未知错误' })
    }
  } catch (error) {
    toast.error('连接测试失败', { description: errorMessage(error) })
  } finally {
    if (testingId.value === server.id) testingId.value = null
  }
}

function formatChecked(value: string | null): string {
  if (!value) return '尚未测试'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div v-if="mode === 'list'" class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">
        共 {{ servers.length }} 个 MCP 服务器 · 仅管理员可配置，成员按会话选用
      </p>
      <div class="flex items-center gap-2">
        <Button variant="outline" class="h-8" :disabled="loading" @click="load">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
        <Button class="h-8" @click="startCreate">
          <Plus class="size-3.5" />
          新增服务器
        </Button>
      </div>
    </div>

    <div v-if="loading" class="overflow-hidden rounded-lg border border-border bg-card">
      <div
        v-for="index in 3"
        :key="index"
        class="flex items-center gap-3 border-t border-border px-4 py-3 first:border-t-0"
      >
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
      <p class="text-sm font-medium">MCP 服务器加载失败</p>
      <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">
        {{ loadError }}
      </p>
      <Button variant="outline" class="mt-4 h-9" @click="load">
        <RefreshCw class="size-4" />
        重试
      </Button>
    </div>

    <div
      v-else-if="!servers.length"
      class="rounded-lg border border-dashed border-border px-4 py-14 text-center"
    >
      <Plug class="mx-auto size-8 text-muted-foreground/60" />
      <p class="mt-3 text-sm font-medium">还没有 MCP 服务器</p>
      <p class="mx-auto mt-1 max-w-[440px] text-sm leading-6 text-muted-foreground">
        添加一个 Streamable HTTP MCP 服务器后，成员可以在输入框旁按会话启用它。
      </p>
      <Button class="mt-4 h-9" @click="startCreate">
        <Plus class="size-4" />
        新增服务器
      </Button>
    </div>

    <div v-else class="overflow-hidden rounded-lg border border-border bg-card">
      <div
        v-for="server in servers"
        :key="server.id"
        class="group/server flex items-start gap-3 border-t border-border px-4 py-3 transition-colors first:border-t-0 hover:bg-muted/40"
      >
        <span
          class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md border border-border bg-background"
        >
          <Plug class="size-4 text-muted-foreground" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="truncate text-[13px] font-medium">{{ server.name }}</p>
            <span
              class="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >{{ server.slug }}</span>
            <span
              v-if="!server.enabled"
              class="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground"
            >已停用</span>
            <span
              v-if="server.requires_approval"
              class="rounded-md bg-brand-soft px-1.5 py-0.5 text-[11px] text-brand"
            >调用需确认</span>
            <span
              v-if="server.defer_loading"
              class="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >按需加载</span>
          </div>
          <p class="mt-1 truncate text-sm text-muted-foreground">{{ server.url }}</p>
          <p class="mt-1 text-xs text-muted-foreground">
            {{ server.description || '未填写说明' }} · {{ server.tool_count }} 个工具 · 最近测试
            {{ formatChecked(server.last_checked_at) }}
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            class="h-8 text-muted-foreground"
            :disabled="testingId !== null"
            @click="test(server)"
          >
            <Loader2 v-if="testingId === server.id" class="size-3.5 animate-spin" />
            测试
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            class="size-8 text-muted-foreground"
            aria-label="编辑 MCP 服务器"
            @click="startEdit(server)"
          >
            <Pencil class="size-4" />
          </Button>
          <template v-if="pendingDeleteId === server.id">
            <Button variant="destructive" size="sm" :disabled="deleting" @click="remove(server)">
              确认删除
            </Button>
            <Button
              variant="ghost"
              size="sm"
              class="text-muted-foreground"
              :disabled="deleting"
              @click="pendingDeleteId = null"
            >
              取消
            </Button>
          </template>
          <Button
            v-else
            variant="ghost"
            size="icon-sm"
            class="size-8 text-muted-foreground hover:text-destructive"
            aria-label="删除 MCP 服务器"
            @click="remove(server)"
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
      <p class="text-sm font-medium">{{ editing ? '编辑 MCP 服务器' : '新增 MCP 服务器' }}</p>
    </div>

    <div class="space-y-4 rounded-lg border border-border bg-card p-4">
      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">名称</span>
        <Input v-model="form.name" maxlength="64" placeholder="例如 GitHub" />
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">slug</span>
        <Input
          v-model="form.slug"
          maxlength="32"
          :disabled="Boolean(editing)"
          placeholder="小写字母/数字/下划线，例如 github"
        />
        <span class="block text-xs text-muted-foreground">
          工具名前缀为 mcp_{{ form.slug || '<slug>' }}__，创建后不建议修改。
        </span>
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">MCP 地址</span>
        <Input v-model="form.url" placeholder="https://example.com/mcp" />
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">说明</span>
        <Input v-model="form.description" maxlength="500" placeholder="给成员看的一句话说明" />
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">Bearer Token</span>
        <Input
          v-model="form.auth"
          type="password"
          autocomplete="new-password"
          :disabled="form.clear_auth"
          :placeholder="
            form.clear_auth
              ? '保存后清除已配置的 token'
              : editing?.has_auth
                ? '已配置；留空表示不修改'
                : '留空表示不需要认证'
          "
        />
      </label>

      <label v-if="editing?.has_auth" class="flex items-center gap-2 text-[13px]">
        <Switch v-model="form.clear_auth" />
        清除已保存的凭证
      </label>

      <label class="block space-y-1.5">
        <span class="text-[12.5px] font-medium">调用超时（秒）</span>
        <Input v-model="form.timeout_seconds" type="number" min="10" max="600" />
      </label>

      <div class="flex flex-wrap items-center gap-6 pt-1">
        <label class="flex items-center gap-2 text-[13px]">
          <Switch v-model="form.enabled" />
          启用
        </label>
        <label class="flex items-center gap-2 text-[13px]">
          <Switch v-model="form.requires_approval" />
          调用前确认
        </label>
        <label class="flex items-center gap-2 text-[13px]">
          <Switch v-model="form.defer_loading" />
          按需加载工具
        </label>
      </div>

      <p v-if="formError" class="text-[12.5px] text-destructive">{{ formError }}</p>

      <div class="flex flex-wrap items-center gap-2">
        <Button :disabled="saving" @click="save">
          <Loader2 v-if="saving" class="size-4 animate-spin" />
          {{ editing ? '保存' : '创建' }}
        </Button>
        <Button
          v-if="editing"
          variant="outline"
          :disabled="testingId !== null"
          @click="test(editing)"
        >
          <Loader2 v-if="testingId === editing.id" class="size-4 animate-spin" />
          测试连接
        </Button>
      </div>

      <div
        v-if="testResult"
        class="rounded-md border border-border bg-background px-3 py-2 text-xs"
      >
        <p :class="testResult.ok ? 'text-foreground' : 'text-destructive'">
          {{ testResult.ok ? `连接成功，发现 ${testResult.tools.length} 个工具` : testResult.error }}
        </p>
        <ul v-if="testResult.tools.length" class="mt-2 space-y-1 text-muted-foreground">
          <li v-for="tool in testResult.tools" :key="tool.name">
            <span class="font-mono text-[11px]">{{ tool.name }}</span>
            <span v-if="tool.description"> · {{ tool.description }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
