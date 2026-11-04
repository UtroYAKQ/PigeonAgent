<script setup lang="ts">
withDefaults(defineProps<{ size?: 'sm' | 'md' | 'lg' }>(), {
  size: 'md',
})
</script>

<template>
  <img
    src="/logo.png"
    alt=""
    aria-hidden="true"
    draggable="false"
    class="shrink-0 select-none object-contain dark:invert"
    :class="size === 'sm' ? 'size-6' : size === 'lg' ? 'size-12' : 'size-8'"
  >
</template>
