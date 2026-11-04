<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'

import { Button } from '@/components/ui/button'

const props = defineProps<{
  offset: number
  limit: number
  total: number
}>()

const emit = defineEmits<{ page: [direction: -1 | 1] }>()

const page = computed(() => Math.floor(props.offset / props.limit) + 1)
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.limit)))
</script>

<template>
  <div class="flex items-center gap-3">
    <p class="text-xs tabular-nums text-muted-foreground">第 {{ page }} / {{ pages }} 页</p>
    <div class="flex items-center gap-1.5">
      <Button
        variant="outline"
        size="icon-sm"
        class="size-8"
        :disabled="offset === 0"
        aria-label="上一页"
        @click="emit('page', -1)"
      >
        <ChevronLeft class="size-4" />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        class="size-8"
        :disabled="props.offset + props.limit >= props.total"
        aria-label="下一页"
        @click="emit('page', 1)"
      >
        <ChevronRight class="size-4" />
      </Button>
    </div>
  </div>
</template>
