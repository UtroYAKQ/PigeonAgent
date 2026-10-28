<script setup lang="ts">
import { Check, Cpu, Plus } from "lucide-vue-next";
import { nextTick, reactive, ref } from "vue";

import { createModel, deleteModel, updateModel } from "../../lib/api";
import { pushToast, reportError } from "../../lib/toast";
import type { LlmModel } from "../../types";

const props = defineProps<{ models: LlmModel[] }>();

const emit = defineEmits<{
  (event: "changed"): void;
}>();

const PROVIDERS = [
  "openai",
  "anthropic",
  "google",
  "deepseek",
  "openrouter",
  "groq",
  "mistral",
  "xai",
  "alibaba",
  "vllm",
  "custom",
];

const content = ref<HTMLElement | null>(null);
const formOpen = ref(false);
const editing = ref<LlmModel | null>(null);
const saving = ref(false);
const deleting = ref<number | null>(null);
const confirmingDelete = ref<number | null>(null);

interface FormState {
  name: string;
  provider: string;
  model_name: string;
  base_url: string;
  api_key: string;
  context_window: string;
  max_output_tokens: string;
  supports_tools: boolean;
  is_active: boolean;
  is_default: boolean;
}

const emptyForm = (): FormState => ({
  name: "",
  provider: "openai",
  model_name: "",
  base_url: "",
  api_key: "",
  context_window: "",
  max_output_tokens: "",
  supports_tools: true,
  is_active: true,
  is_default: false,
});

const form = reactive<FormState>(emptyForm());

async function revealForm(): Promise<void> {
  await nextTick();
  content.value?.scrollTo({ top: 0, behavior: "smooth" });
}

function startCreate(): void {
  Object.assign(form, emptyForm());
  editing.value = null;
  formOpen.value = true;
  void revealForm();
}

function startEdit(model: LlmModel): void {
  Object.assign(form, {
    name: model.name,
    provider: model.provider,
    model_name: model.model_name,
    base_url: model.base_url ?? "",
    api_key: "",
    context_window: model.context_window == null ? "" : String(model.context_window),
    max_output_tokens: model.max_output_tokens == null ? "" : String(model.max_output_tokens),
    supports_tools: model.supports_tools,
    is_active: model.is_active,
    is_default: model.is_default,
  });
  editing.value = model;
  formOpen.value = true;
  void revealForm();
}

function optionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.floor(parsed);
}

async function save(): Promise<void> {
  if (!form.name.trim() || !form.model_name.trim()) {
    pushToast("名称和上游模型名不能为空");
    return;
  }
  saving.value = true;
  const payload: Record<string, unknown> = {
    name: form.name.trim(),
    provider: form.provider,
    model_name: form.model_name.trim(),
    base_url: form.base_url.trim() || null,
    context_window: optionalNumber(form.context_window),
    max_output_tokens: optionalNumber(form.max_output_tokens),
    supports_tools: form.supports_tools,
    is_active: form.is_active,
    is_default: form.is_default,
  };
  if (form.api_key.trim()) payload.api_key = form.api_key.trim();
  try {
    if (editing.value) await updateModel(editing.value.id, payload);
    else await createModel(payload);
    emit("changed");
    formOpen.value = false;
    editing.value = null;
  } catch (cause) {
    reportError(cause);
  } finally {
    saving.value = false;
  }
}

async function remove(model: LlmModel): Promise<void> {
  if (confirmingDelete.value !== model.id) {
    confirmingDelete.value = model.id;
    return;
  }
  deleting.value = model.id;
  try {
    await deleteModel(model.id);
    emit("changed");
    if (editing.value?.id === model.id) {
      formOpen.value = false;
      editing.value = null;
    }
  } catch (cause) {
    reportError(cause);
  } finally {
    deleting.value = null;
    confirmingDelete.value = null;
  }
}

function providerBadge(provider: string): string {
  return provider.slice(0, 2).toUpperCase();
}

function contextLabel(model: LlmModel): string {
  if (!model.context_window) return "上下文未设置";
  return `${model.context_window.toLocaleString()} 上下文`;
}
</script>

<template>
  <div ref="content" class="h-full overflow-y-auto px-5 py-5">
    <div class="flex items-start gap-3">
      <div>
        <h3 class="text-ui font-medium text-ink">模型配置</h3>
        <p class="mt-0.5 text-meta text-faint">
          API Key 只加密存储在服务端，编辑时留空表示保持不变。
        </p>
      </div>
      <button class="btn btn-primary ml-auto shrink-0" @click="startCreate">
        <Plus :size="14" :stroke-width="2" />
        添加模型
      </button>
    </div>

    <section v-if="formOpen" class="mt-4 rounded-surface border border-hair bg-inset/40 p-4">
      <div class="flex items-center gap-2">
        <h4 class="text-ui font-medium text-ink">
          {{ editing ? "编辑模型" : "添加模型" }}
        </h4>
        <span v-if="editing" class="truncate font-mono text-micro text-faint">
          {{ editing.name }}
        </span>
        <button
          class="ml-auto text-meta text-faint transition-colors hover:text-ink"
          @click="formOpen = false"
        >
          取消
        </button>
      </div>
      <div class="mt-3 grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-meta text-faint">显示名称</span>
          <input v-model="form.name" placeholder="例如 GPT-4o" class="input" />
        </label>
        <label class="block">
          <span class="mb-1 block text-meta text-faint">Provider</span>
          <select v-model="form.provider" class="input">
            <option v-for="provider in PROVIDERS" :key="provider" :value="provider">
              {{ provider }}
            </option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-meta text-faint">上游模型名</span>
          <input v-model="form.model_name" placeholder="gpt-4o-mini" class="input font-mono" />
        </label>
        <label class="block">
          <span class="mb-1 block text-meta text-faint">Base URL（可选）</span>
          <input
            v-model="form.base_url"
            placeholder="https://api.openai.com/v1"
            class="input font-mono"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-meta text-faint">
            API Key {{ editing ? "（留空不修改）" : "" }}
          </span>
          <input
            v-model="form.api_key"
            type="password"
            placeholder="sk-..."
            class="input font-mono"
          />
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span class="mb-1 block text-meta text-faint">上下文窗口</span>
            <input
              v-model="form.context_window"
              inputmode="numeric"
              placeholder="128000"
              class="input font-mono"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-meta text-faint">最大输出</span>
            <input
              v-model="form.max_output_tokens"
              inputmode="numeric"
              placeholder="8192"
              class="input font-mono"
            />
          </label>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-4 text-meta text-muted">
        <label class="flex items-center gap-1.5">
          <input v-model="form.supports_tools" type="checkbox" class="size-3.5 accent-ink" />
          支持工具
        </label>
        <label class="flex items-center gap-1.5">
          <input v-model="form.is_active" type="checkbox" class="size-3.5 accent-ink" />
          启用
        </label>
        <label class="flex items-center gap-1.5">
          <input v-model="form.is_default" type="checkbox" class="size-3.5 accent-ink" />
          设为默认
        </label>
        <button class="btn btn-primary ml-auto" :disabled="saving" @click="save">
          <Check v-if="!saving" :size="13" />
          {{ saving ? "保存中…" : "保存模型" }}
        </button>
      </div>
    </section>

    <div
      v-if="props.models.length === 0 && !formOpen"
      class="mt-6 rounded-float border border-dashed border-hair px-5 py-10 text-center"
    >
      <Cpu :size="24" class="mx-auto text-faint" :stroke-width="1.4" />
      <p class="mt-3 text-ui text-muted">还没有模型</p>
      <p class="mt-1 text-meta text-faint">
        添加一个 OpenAI、Anthropic 或自托管模型后开始聊天。
      </p>
      <button class="btn btn-primary mt-4" @click="startCreate">添加第一个模型</button>
    </div>

    <div v-else class="mt-4 grid gap-2.5 sm:grid-cols-2">
      <div
        v-for="model in models"
        :key="model.id"
        class="group rounded-surface border border-hair bg-canvas p-3.5 transition-colors hover:border-ink/15"
      >
        <div class="flex items-start gap-2.5">
          <div
            class="grid size-8 shrink-0 place-items-center rounded-control bg-inset font-mono text-micro font-semibold text-muted"
          >
            {{ providerBadge(model.provider) }}
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-1.5">
              <span class="truncate text-ui font-medium text-ink">{{ model.name }}</span>
              <span
                v-if="model.is_default"
                class="rounded-full bg-accent-soft px-1.5 py-0.5 text-micro text-accent"
              >
                默认
              </span>
              <span
                v-if="!model.is_active"
                class="rounded-full bg-hover px-1.5 py-0.5 text-micro text-faint"
              >
                停用
              </span>
            </div>
            <p class="mt-0.5 truncate font-mono text-micro text-faint">
              {{ model.provider }} / {{ model.model_name }}
            </p>
            <p class="mt-1 text-micro text-faint">
              {{ contextLabel(model) }}
              <span v-if="model.supports_tools"> · 工具</span>
            </p>
          </div>
          <div
            class="ml-auto flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-md:opacity-100"
          >
            <button
              class="rounded-control px-1.5 py-1 text-micro text-muted hover:bg-hover hover:text-ink"
              @click="startEdit(model)"
            >
              编辑
            </button>
            <button
              :class="[
                'rounded-control px-1.5 py-1 text-micro',
                confirmingDelete === model.id
                  ? 'bg-warn/10 text-warn'
                  : 'text-faint hover:bg-hover hover:text-warn',
              ]"
              :disabled="deleting === model.id"
              @click="remove(model)"
            >
              {{ confirmingDelete === model.id ? "确认删除" : "删除" }}
            </button>
          </div>
        </div>
        <p
          v-if="model.base_url"
          class="mt-2 truncate rounded-control bg-inset px-2 py-1 font-mono text-micro text-faint"
        >
          {{ model.base_url }}
        </p>
      </div>
    </div>
  </div>
</template>
