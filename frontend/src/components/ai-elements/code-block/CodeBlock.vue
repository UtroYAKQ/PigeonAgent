<script setup lang="ts">
import type { BundledLanguage, SpecialLanguage } from 'shiki'
import type { HTMLAttributes } from 'vue'
import CodeBlockContainer from './CodeBlockContainer.vue'
import CodeBlockContent from './CodeBlockContent.vue'

const props = withDefaults(
  defineProps<{
    code: string
    language: BundledLanguage | SpecialLanguage
    showLineNumbers?: boolean
    wrap?: boolean
    class?: HTMLAttributes['class']
  }>(),
  {
    showLineNumbers: false,
    wrap: false,
  },
)
</script>

<template>
  <CodeBlockContainer :class="props.class" :language="props.language">
    <slot />
    <CodeBlockContent
      :code="props.code"
      :language="props.language"
      :show-line-numbers="props.showLineNumbers"
      :wrap="props.wrap"
    />
  </CodeBlockContainer>
</template>
