<script setup lang="ts">
import { Paperclip } from '@lucide/vue'

import type { ArtifactMedia } from '@/lib/turnModel'
import FileAttachment from './FileAttachment.vue'

/**
 * 回合末尾的产出。
 *
 * 文件类产物不占正文版面，统一收在这里；卡片尺寸与输入气泡里的附件保持一致。
 */
defineProps<{ media: ArtifactMedia[] }>()

function displayName(item: ArtifactMedia): string {
  if (item.name) return item.name
  if (item.alt) return `${item.alt.slice(0, 24)}.png`
  return item.kind === 'image' ? '生成的图片' : '文件'
}
</script>

<template>
  <section v-if="media.length" class="not-prose mt-4">
    <div class="mb-2 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
      <Paperclip class="size-3.5" :stroke-width="1.8" />
      <span>产出文件</span>
      <span class="text-muted-foreground/60">{{ media.length }}</span>
    </div>

    <div class="flex flex-wrap gap-2">
      <FileAttachment
        v-for="item in media"
        :key="item.id"
        :name="displayName(item)"
        :size="item.size"
        :media-type="item.mediaType"
        :file-id="item.fileId"
        :data="item.data"
      />
    </div>
  </section>
</template>
