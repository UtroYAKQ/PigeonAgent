<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="space-y-4">
    <div>
      <h2 class="text-lg font-medium">{{ title }}</h2>
      <p v-if="description" class="mt-1 max-w-[70ch] text-sm leading-6 text-muted-foreground">
        {{ description }}
      </p>
    </div>
    <div class="h-px bg-border" />
    <div>
      <slot />
    </div>
  </section>
</template>
