<script setup lang="ts">
import { computed } from 'vue'
import type { BundledLanguage, SpecialLanguage } from 'shiki'
import { ExternalLink, Maximize2 } from '@lucide/vue'

import { CodeBlock, CodeBlockHeader } from '@/components/ai-elements/code-block'
import { TooltipHint } from '@/components/ui/tooltip'
import { formatHtml } from '@/lib/code'
import { PREVIEW_TOOL, parsePreviewArgs } from '@/lib/frontendTools'
import { parseJsonLike, stringifyValue } from '@/lib/format'
import {
  commandFromStep,
  fileLanguage,
  findMedia,
  terminalFromStep,
  type ToolStep,
} from '@/lib/tools'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'
import AuthMedia from './AuthMedia.vue'
import FileAttachment from './FileAttachment.vue'
import TerminalPanel from './TerminalPanel.vue'
import ToolCodeCopy from './ToolCodeCopy.vue'

const props = defineProps<{ step: ToolStep }>()
const chat = useChatStore()
const panels = usePanelStore()

const preview = computed(() =>
  props.step.name === PREVIEW_TOOL ? parsePreviewArgs(props.step.args) : null,
)
const previewHtml = computed(() => (preview.value ? formatHtml(preview.value.html) : ''))

function openPreview(): void {
  if (!preview.value || !chat.currentSessionId) return
  panels.openPreview({
    sessionId: chat.currentSessionId,
    toolCallId: props.step.id,
    title: preview.value.title,
    html: preview.value.html,
  })
}

function openSource(): void {
  if (!preview.value || !chat.currentSessionId) return
  panels.openTab({
    sessionId: chat.currentSessionId,
    type: 'code',
    title: `${preview.value.title} · 源码`,
    content: previewHtml.value,
    language: 'html',
    sourceId: props.step.id,
  })
}

const command = computed(() => commandFromStep(props.step))
const terminal = computed(() => terminalFromStep(props.step))
const media = computed(() => (props.step.result != null ? findMedia(props.step.result) : []))

/** write_file 的 args 是 { name, content }；content 里是真正的换行，按文件内容渲染而不是整段 JSON。 */
interface WrittenFile {
  name: string
  content: string
  language: BundledLanguage | SpecialLanguage
}

function decodeJsonEscapes(source: string): string {
  let out = ''
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index]
    if (char !== '\\') {
      out += char
      continue
    }
    const next = source[index + 1]
    if (next === undefined) break
    index += 1
    if (next === 'u') {
      const hex = source.slice(index + 1, index + 5)
      if (/^[0-9a-f]{4}$/i.test(hex)) {
        out += String.fromCharCode(Number.parseInt(hex, 16))
        index += 4
      } else {
        out += '\\u'
      }
      continue
    }
    const escapes: Record<string, string> = {
      n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', '"': '"', '\\': '\\', '/': '/',
    }
    out += escapes[next] ?? next
  }
  return out
}

function completeJsonString(raw: string, key: string): string | null {
  const match = new RegExp(`"${key}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`).exec(raw)
  return match ? decodeJsonEscapes(match[1] ?? '') : null
}

function partialJsonString(raw: string, key: string): string | null {
  const match = new RegExp(`"${key}"\\s*:\\s*"`).exec(raw)
  if (!match) return null
  const start = match.index + match[0].length
  let end = raw.length
  let escaped = false
  for (let index = start; index < raw.length; index += 1) {
    const char = raw[index]
    if (escaped) {
      escaped = false
      continue
    }
    if (char === '\\') {
      escaped = true
      continue
    }
    if (char === '"') {
      end = index
      break
    }
  }
  return decodeJsonEscapes(raw.slice(start, end))
}

function writtenFileFromPartial(raw: string): WrittenFile | null {
  const name = completeJsonString(raw, 'name')
  const content = partialJsonString(raw, 'content')
  if (name === null && content === null) return null
  const filename = name ?? '写入内容'
  return {
    name: filename,
    content: content ?? '',
    language: fileLanguage(name, content ?? ''),
  }
}

const writtenFile = computed<WrittenFile | null>(() => {
  if (props.step.name !== 'write_file') return null
  const raw = props.step.args
  const parsed = typeof raw === 'string' ? parseJsonLike(raw) : raw
  if (parsed && typeof parsed === 'object') {
    const data = parsed as Record<string, unknown>
    if (typeof data.content !== 'string') return null
    const writtenName = typeof data.name === 'string' ? data.name : null
    return {
      name: writtenName ?? '写入内容',
      content: data.content,
      language: fileLanguage(writtenName, data.content),
    }
  }
  return typeof raw === 'string' ? writtenFileFromPartial(raw) : null
})

const writeFileNote = computed(() => {
  const name = writtenFile.value?.name
  if (props.step.state === 'running' || props.step.state === 'waiting') {
    return name ? `正在生成 ${name} 的内容…` : '正在生成文件内容…'
  }
  if (props.step.state === 'success') return name ? `${name} 的内容为空` : '文件内容为空'
  return name ? `${name} 的写入已暂停` : '写入已暂停，暂无可展示的内容'
})

const fallback = computed<{ text: string; language: BundledLanguage | SpecialLanguage } | null>(() => {
  if (props.step.result == null) return null
  const parsed = props.step.result
  return {
    text: typeof parsed === 'string' ? parsed : stringifyValue(parsed),
    language: typeof parsed === 'string' ? 'text' : 'json',
  }
})

const args = computed(() => {
  if (props.step.args == null || props.step.args === '') return null
  return typeof props.step.args === 'string' ? props.step.args : stringifyValue(props.step.args)
})
</script>

<template>
  <div class="space-y-2">
    <div
      v-if="preview"
      class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface/60 px-3 py-2"
    >
      <span class="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground">
        <Maximize2 class="size-3.5" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-[12.5px] font-medium text-foreground">{{ preview.title || '页面预览' }}</p>
        <p class="text-[11px] text-muted-foreground">HTML 页面 · 在预览面板查看</p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <TooltipHint text="在侧栏展开 HTML 源码">
          <button
            type="button"
            class="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            aria-label="在侧栏展开 HTML 源码"
            @click="openSource"
          >
            <Maximize2 class="size-3" />
            源码
          </button>
        </TooltipHint>
        <TooltipHint text="打开页面预览">
          <button
            type="button"
            class="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            aria-label="打开页面预览"
            @click="openPreview"
          >
            <ExternalLink class="size-3" />
            预览
          </button>
        </TooltipHint>
        <ToolCodeCopy :code="previewHtml" />
      </div>
    </div>

    <template v-else>
    <CodeBlock
      v-if="command"
      :code="command"
      language="bash"
      wrap
      class="pigeon-code overflow-hidden rounded-lg border-border bg-code shadow-none"
    >
      <CodeBlockHeader class="h-8 border-b border-border bg-transparent px-3 py-0">
        <span class="font-mono text-[11px]">bash</span>
        <ToolCodeCopy :code="command ?? ''" />
      </CodeBlockHeader>
    </CodeBlock>

    <TerminalPanel
      v-if="terminal"
      :stdout="terminal.stdout"
      :stderr="terminal.stderr"
      :exit-code="terminal.exitCode"
    />

    <div v-else-if="media.length" class="flex flex-wrap gap-2">
      <template v-for="(item, index) in media" :key="index">
        <AuthMedia
          v-if="item.kind === 'image' || item.kind === 'video'"
          :kind="item.kind"
          :data="item.data"
          :src="item.url"
          :media-type="item.mediaType"
          fit="contain"
          class="max-h-64 w-full max-w-[420px] rounded-lg border border-border"
        />
        <FileAttachment
          v-else-if="item.kind === 'resource' && item.fileId && item.name"
          :name="item.name"
          :size="item.size"
          :media-type="item.mediaType"
          :file-id="item.fileId"
        />
      </template>
    </div>

    <CodeBlock
      v-else-if="fallback"
      :code="fallback.text"
      :language="fallback.language"
      wrap
      class="pigeon-code overflow-hidden rounded-lg border-border bg-code shadow-none"
    >
      <CodeBlockHeader class="h-8 border-b border-border bg-transparent px-3 py-0">
        <span class="font-mono text-[11px]">{{ step.result != null && step.state === 'failed' ? 'error' : 'output' }}</span>
        <ToolCodeCopy :code="fallback?.text ?? ''" />
      </CodeBlockHeader>
    </CodeBlock>

    <template v-else-if="step.name === 'write_file'">
      <CodeBlock
        v-if="writtenFile?.content"
        :code="writtenFile.content"
        :language="writtenFile.language"
        wrap
        class="pigeon-code overflow-hidden rounded-lg border-border bg-code shadow-none"
      >
        <CodeBlockHeader class="h-8 border-b border-border bg-transparent px-3 py-0">
          <div class="flex min-w-0 items-center gap-2">
            <span class="min-w-0 truncate font-mono text-[11px]">{{ writtenFile.name }}</span>
          </div>
          <ToolCodeCopy :code="writtenFile.content" />
        </CodeBlockHeader>
      </CodeBlock>
      <div
        v-else
        class="rounded-lg border border-border bg-surface px-3 py-2 text-[11.5px] text-muted-foreground"
      >
        {{ writeFileNote }}
      </div>
    </template>

    <CodeBlock
      v-else-if="args"
      :code="args"
      language="json"
      wrap
      class="pigeon-code overflow-hidden rounded-lg border-border bg-code shadow-none"
    >
      <CodeBlockHeader class="h-8 border-b border-border bg-transparent px-3 py-0">
        <span class="font-mono text-[11px]">参数</span>
        <ToolCodeCopy :code="args ?? ''" />
      </CodeBlockHeader>
    </CodeBlock>
    </template>
  </div>
</template>
