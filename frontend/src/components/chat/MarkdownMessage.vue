<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import MarkdownRender, {
  enableKatex,
  enableMermaid,
  setCustomComponents,
  type MarkdownIt,
} from 'markstream-vue'
import 'katex/dist/katex.min.css'

import { copyToClipboard } from '@/lib/clipboard'
import { useChatStore } from '@/stores/chat'
import { usePanelStore } from '@/stores/panel'
import { useUiStore } from '@/stores/ui'
import MarkdownCodeBlock from './MarkdownCodeBlock.vue'

const props = withDefaults(defineProps<{
  content: string
  streaming?: boolean
}>(), {
  streaming: false,
})

const CUSTOM_ID = 'pigeon-markdown'

// 公式和 Mermaid 图由 markstream 按需加载；D2 / Infographic 没装依赖，继续当代码块
enableKatex()
enableMermaid()

setCustomComponents(CUSTOM_ID, {
  code_block: MarkdownCodeBlock,
  d2: MarkdownCodeBlock,
  infographic: MarkdownCodeBlock,
})

/** 与旧 markdown-it 配置保持一致：单换行断行、自动链接、不转排印符号、原始 HTML 按文本处理。 */
function configureMarkdown(md: MarkdownIt): MarkdownIt {
  md.set({ breaks: true, typographer: false, html: false, linkify: true })
  return md
}

const chat = useChatStore()
const panels = usePanelStore()
const ui = useUiStore()

let labelTimer: number | null = null

function clearLabelTimer(): void {
  if (labelTimer !== null) {
    window.clearTimeout(labelTimer)
    labelTimer = null
  }
}

onBeforeUnmount(clearLabelTimer)

async function onClick(event: MouseEvent): Promise<void> {
  const target = event.target
  if (!(target instanceof Element)) return

  const expandButton = target.closest('.md-code__expand')
  if (expandButton) {
    const container = expandButton.closest('.md-code')
    const code = container?.querySelector('pre')?.textContent ?? ''
    if (!code || !chat.currentSessionId) return
    const language = container
      ?.querySelector('.md-code__header > span')
      ?.textContent?.trim() || 'text'
    panels.openTab({
      sessionId: chat.currentSessionId,
      type: 'code',
      title: language === 'text' ? '代码' : `${language} 代码`,
      content: code,
      language,
    })
    return
  }

  const button = target.closest('.md-code__copy')
  if (!button) return
  const container = button.closest('.md-code')
  const code = container?.querySelector('pre')?.textContent ?? ''
  if (!(await copyToClipboard(code))) return
  const label = button.querySelector('span')
  if (label) {
    const previous = label.textContent
    label.textContent = '已复制'
    clearLabelTimer()
    labelTimer = window.setTimeout(() => {
      label.textContent = previous
      labelTimer = null
    }, 1400)
  }
}
</script>

<template>
  <div
    class="markdown"
    :class="{ 'markdown-wrap-code': ui.wrapCode }"
    @click="onClick"
  >
    <MarkdownRender
      :content="props.content"
      :final="!props.streaming"
      mode="chat"
      :custom-id="CUSTOM_ID"
      html-policy="escape"
      :custom-markdown-it="configureMarkdown"
      :is-dark="ui.isDark"
    />
  </div>
</template>
