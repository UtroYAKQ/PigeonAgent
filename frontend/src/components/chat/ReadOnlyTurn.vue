<script setup lang="ts">
import { AlertTriangle } from '@lucide/vue'

import { hasAssistantOutput, type TurnView } from '@/lib/turnModel'
import { useUiStore } from '@/stores/ui'
import ArtifactBlock from './ArtifactBlock.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import SourcesRow from './SourcesRow.vue'
import ThinkingChain from './ThinkingChain.vue'
import TurnFiles from './TurnFiles.vue'

const props = defineProps<{
  view: TurnView
  streaming?: boolean
}>()

const ui = useUiStore()
</script>

<template>
  <article class="flex flex-col gap-4">
    <div v-if="props.view.userText" class="ml-auto max-w-[85%]">
      <div class="rounded-2xl bg-surface px-4 py-3 text-[14px] leading-7 whitespace-pre-wrap break-words">
        {{ props.view.userText }}
      </div>
    </div>

    <div class="min-w-0">
      <template v-for="segment in props.view.segments" :key="segment.id">
        <ThinkingChain
          v-if="segment.kind === 'chain'"
          :chain="segment.entries"
          :is-streaming="Boolean(props.streaming)"
          :status="props.view.status"
          :default-open="ui.autoExpandThinking"
          :default-details-open="ui.autoExpandToolDetails"
        />
        <ArtifactBlock
          v-else-if="segment.kind === 'artifact'"
          :media="segment.media"
          :credits="segment.credits"
        />
        <MarkdownMessage v-else :content="segment.text" />
      </template>

      <TurnFiles v-if="props.view.attachments.length" :media="props.view.attachments" />

      <SourcesRow v-if="props.view.sources.length" :sources="props.view.sources" />

      <div
        v-if="props.view.error || (!hasAssistantOutput(props.view) && props.view.userText)"
        class="mt-3 flex items-start gap-2 text-[12px] leading-5 text-muted-foreground"
      >
        <AlertTriangle class="mt-0.5 size-3.5 shrink-0" />
        <span class="min-w-0 flex-1">
          {{ props.view.error?.message || '这一轮没有可展示的内容。' }}
        </span>
      </div>
    </div>
  </article>
</template>