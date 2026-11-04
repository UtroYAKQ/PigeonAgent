<script setup lang="ts">
import { computed } from 'vue'
import type { BundledLanguage } from 'shiki'

import { CodeBlock } from '@/components/ai-elements/code-block'
import { guardPreviewDocument } from '@/lib/previewDocument'
import type { PanelTab } from '@/types/panel'
import MarkdownMessage from './MarkdownMessage.vue'

const props = defineProps<{ tab: PanelTab }>()

const codeLanguage = computed(() => (props.tab.language || 'text') as BundledLanguage)
const previewSrcdoc = computed(() =>
  props.tab.type === 'html' ? guardPreviewDocument(props.tab.content) : '',
)
</script>

<template>
  <iframe
    v-if="tab.type === 'html'"
    :key="tab.id"
    :srcdoc="previewSrcdoc"
    sandbox="allow-scripts"
    referrerpolicy="no-referrer"
    class="h-full w-full rounded-xl border border-border bg-white"
    :title="tab.title"
  />

  <div
    v-else-if="tab.type === 'code'"
    class="h-full overflow-hidden rounded-xl border border-border bg-code"
  >
    <CodeBlock
      :code="tab.content"
      :language="codeLanguage"
      show-line-numbers
      class="panel-code pigeon-code h-full bg-code"
    />
  </div>

  <div v-else class="h-full overflow-y-auto rounded-xl border border-border bg-background px-6 py-5">
    <MarkdownMessage :content="tab.content" />
  </div>
</template>
