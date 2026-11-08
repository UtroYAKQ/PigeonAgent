<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { useSiteStore } from '@/stores/site'

withDefaults(defineProps<{ size?: 'sm' | 'md' | 'lg' }>(), {
  size: 'md',
})

const site = useSiteStore()
const failed = ref(false)

watch(() => site.logoUrl, () => { failed.value = false })

const custom = computed(() => Boolean(site.logoUrl) && !failed.value)
const src = computed(() => (custom.value ? site.logoUrl! : '/logo.png'))
</script>

<template>
  <img
    :src="src"
    alt=""
    aria-hidden="true"
    draggable="false"
    class="shrink-0 select-none object-contain"
    :class="[
      size === 'sm' ? 'size-6' : size === 'lg' ? 'size-12' : 'size-8',
      custom ? '' : 'dark:invert',
    ]"
    @error="failed = true"
  >
</template>
