<script setup lang="ts">
import { computed } from 'vue'

import AuthMedia from '@/components/chat/AuthMedia.vue'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    shape?: 'rounded' | 'circle'
  }>(),
  {
    size: 'md',
    shape: 'rounded',
  },
)

const auth = useAuthStore()

const initials = computed(() => {
  const source = auth.user?.display_name || auth.user?.email || '我'
  return source.slice(0, 1).toUpperCase()
})

const sizeClass = computed(
  () => ({
    sm: 'size-8 text-xs',
    md: 'size-10 text-sm',
    lg: 'size-12 text-base',
  })[props.size],
)
</script>

<template>
  <span
    class="grid shrink-0 place-items-center overflow-hidden border border-border bg-background font-medium"
    :class="[sizeClass, shape === 'circle' ? 'rounded-full' : 'rounded-md']"
  >
    <AuthMedia
      v-if="auth.user?.avatar_file_id"
      :file-id="auth.user.avatar_file_id"
      fit="cover"
      compact
      class="size-full"
    />
    <template v-else>{{ initials }}</template>
  </span>
</template>
