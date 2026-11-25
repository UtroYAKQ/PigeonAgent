<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { AlertTriangle } from '@lucide/vue'

const failed = ref(false)
const reason = ref('')

onErrorCaptured((error) => {
  failed.value = true
  reason.value = error instanceof Error ? error.message : String(error)
  console.error('Turn block render failed', error)
  return false
})
</script>

<template>
  <div
    v-if="failed"
    class="my-3 flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/[0.04] px-3 py-2 text-[12px] leading-5 text-muted-foreground"
  >
    <AlertTriangle class="mt-0.5 size-3.5 shrink-0 text-destructive" />
    <span class="min-w-0 flex-1">这部分内容渲染失败{{ reason ? `：${reason}` : '' }}</span>
  </div>
  <slot v-else />
</template>