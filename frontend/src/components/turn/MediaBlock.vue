<script setup lang="ts">
import type { ArtifactMedia } from '@/lib/turn/types'
import ArtifactBlock from '@/components/chat/ArtifactBlock.vue'
import ArtifactSkeleton from '@/components/chat/ArtifactSkeleton.vue'

defineProps<{
  media: ArtifactMedia[]
  state: 'ready' | 'pending'
}>()
</script>

<template>
  <ArtifactSkeleton v-if="state === 'pending' && !media.length" />
  <ArtifactBlock v-else-if="media.length" :media="media" />
</template>