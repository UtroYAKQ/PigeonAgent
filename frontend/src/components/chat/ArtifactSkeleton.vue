<script setup lang="ts">
import { Image as ImageIcon } from '@lucide/vue'

/**
 * 出图期间的占位。
 *
 * 出图步骤已经从思维链里摘掉了，总得有个东西告诉用户「在做了」。
 * 尺寸（含边框）和出图后的卡片完全一致，图来了原地替换，不会跳。
 *
 * 不用通用 Skeleton：浅色主题下 --muted 是 #f7f7f8，和 #ffffff 的背景几乎同色，
 * 光靠 opacity 脉冲在白底上等于没有——所以这里自己画：边框给轮廓，扫光给动感。
 */
withDefaults(defineProps<{ label?: string }>(), { label: '正在生成图片…' })
</script>

<template>
  <div class="my-4">
    <div
      class="relative h-[150px] w-[175px] overflow-hidden rounded-lg border border-border bg-surface"
    >
      <div
        class="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-foreground/[0.09] to-transparent"
      />
      <div class="relative grid h-full place-items-center">
        <ImageIcon class="size-5 text-muted-foreground" :stroke-width="1.6" />
      </div>
    </div>
    <p class="mt-1.5 text-[11px] text-muted-foreground">{{ label }}</p>
  </div>
</template>
