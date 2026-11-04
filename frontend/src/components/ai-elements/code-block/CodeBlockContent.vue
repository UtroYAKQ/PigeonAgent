<script setup lang="ts">
import type { BundledLanguage, SpecialLanguage, ThemedToken } from 'shiki'
import type { SettledCode, TokenizedCode } from './utils'
import { useThrottleFn } from '@vueuse/core'
import { cn } from '@/lib/utils'
import { normalizeLanguage } from '@/lib/highlighter'
import { computed, ref, watch } from 'vue'
import {
  appendRawTail,
  createRawTokens,
  isBold,
  isItalic,
  isUnderline,
  peekTokens,
  tokenize,
} from './utils'

const props = withDefaults(
  defineProps<{
    code: string
    language: BundledLanguage | SpecialLanguage
    showLineNumbers?: boolean
    wrap?: boolean
  }>(),
  {
    showLineNumbers: false,
    wrap: false,
  },
)

// 参数是一个 token 一个 token 涨上来的：整段重跑 Shiki 既慢，又会把已有颜色闪回纯文本
const HIGHLIGHT_THROTTLE_MS = 200

const settled = ref<SettledCode | null>(null)
const rawTokens = computed<TokenizedCode>(() => createRawTokens(props.code))

const tokenized = computed<TokenizedCode>(() => {
  const base = settled.value
  if (!base || base.language !== normalizeLanguage(props.language)) return rawTokens.value
  if (base.code === props.code) return base.tokens
  // args 被整体替换时前缀已经对不上，退回纯文本等下一次高亮
  if (!props.code.startsWith(base.code)) return rawTokens.value
  return appendRawTail(base.tokens, props.code.slice(base.code.length))
})

const runHighlight = useThrottleFn(async () => {
  const code = props.code
  const language = normalizeLanguage(props.language)
  const result = await tokenize(code, props.language)
  if (!result) return
  // 高亮是异步的，回来时文本可能又长了甚至换了语言
  if (language !== normalizeLanguage(props.language) || !props.code.startsWith(code)) return
  settled.value = { code, language, tokens: result }
}, HIGHLIGHT_THROTTLE_MS, true, true)

watch(
  () => [props.code, props.language] as const,
  () => {
    const cached = peekTokens(props.code, props.language)
    if (cached) {
      settled.value = {
        code: props.code,
        language: normalizeLanguage(props.language),
        tokens: cached,
      }
      return
    }
    void runHighlight()
  },
  { immediate: true },
)

const preStyle = computed(() => ({
  backgroundColor: tokenized.value.bg,
  color: tokenized.value.fg,
}))

interface KeyedToken {
  token: ThemedToken
  key: string
}
interface KeyedLine {
  tokens: KeyedToken[]
  key: string
}

const keyedLines = computed<KeyedLine[]>(() =>
  tokenized.value.tokens.map((line, lineIdx) => ({
    key: `line-${lineIdx}`,
    tokens: line.map((token, tokenIdx) => ({
      token,
      key: `line-${lineIdx}-${tokenIdx}`,
    })),
  })),
)

const lineNumberClasses = cn(
  'block',
  'before:content-[counter(line)]',
  'before:inline-block',
  'before:[counter-increment:line]',
  'before:w-8',
  'before:mr-4',
  'before:text-right',
  'before:text-muted-foreground/50',
  'before:font-mono',
  'before:select-none',
)
</script>

<template>
  <div class="relative" :class="props.wrap ? 'overflow-x-hidden' : 'overflow-auto'">
    <pre
      :class="cn(
        'dark:bg-(--shiki-dark-bg)! dark:text-(--shiki-dark)! m-0 p-4 text-sm',
        props.wrap && 'whitespace-pre-wrap [overflow-wrap:anywhere]',
      )"
      :style="preStyle"
    ><code
        :class="cn(
          'font-mono text-sm',
          showLineNumbers && '[counter-increment:line_0] [counter-reset:line]',
        )"
      ><template v-for="line in keyedLines" :key="line.key"><!-- Line rendering component --><span :class="showLineNumbers ? lineNumberClasses : 'block'"><template v-if="line.tokens.length === 0">{{ '\n' }}</template><template v-else><!-- Token rendering component --><span
                v-for="tokenObj in line.tokens"
                :key="tokenObj.key"
                class="dark:bg-(--shiki-dark-bg)! dark:text-(--shiki-dark)!"
                :style="{
                  color: tokenObj.token.color,
                  backgroundColor: tokenObj.token.bgColor,
                  ...tokenObj.token.htmlStyle,
                  fontStyle: isItalic(tokenObj.token.fontStyle) ? 'italic' : undefined,
                  fontWeight: isBold(tokenObj.token.fontStyle) ? 'bold' : undefined,
                  textDecoration: isUnderline(tokenObj.token.fontStyle) ? 'underline' : undefined,
                }"
    >{{ tokenObj.token.content }}</span></template></span></template></code></pre>
  </div>
</template>
