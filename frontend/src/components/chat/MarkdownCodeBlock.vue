<script setup lang="ts">
import { computed } from 'vue'

import { highlightCode, highlightEpoch } from '@/lib/highlighter'

interface CodeBlockNode {
  language?: string
  code: string
  loading?: boolean
}

const props = defineProps<{
  node: CodeBlockNode
  loading?: boolean
}>()

// 尾部还没闭合的长代码块不逐次跑 Shiki，等闭合后再一次性上色
const MAX_PENDING_HIGHLIGHT_CHARS = 4000

const language = computed(() => {
  const value = (props.node.language || 'text').trim().split(/\s+/)[0]?.toLowerCase()
  return !value || value === 'plaintext' ? 'text' : value
})

const streaming = computed(() => props.node.loading === true || props.loading === true)

const bodyHtml = computed(() => {
  // 语法按需加载完成后重新高亮
  void highlightEpoch.value
  const plain = streaming.value && props.node.code.length > MAX_PENDING_HIGHLIGHT_CHARS
  return highlightCode(props.node.code, language.value, plain)
})
</script>

<template>
  <div class="md-code">
    <div class="md-code__header">
      <span>{{ language }}</span>
      <div class="md-code__actions">
        <button
          type="button"
          class="md-code__expand"
          data-expand-code
          aria-label="在侧栏展开代码"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6" /><path d="M9 21H3v-6" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" /></svg>
          <span>展开</span>
        </button>
        <button
          type="button"
          class="md-code__copy"
          data-copy-code
          aria-label="复制代码"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
          <span>复制</span>
        </button>
      </div>
    </div>
    <div class="md-code__body" v-html="bodyHtml" />
  </div>
</template>
