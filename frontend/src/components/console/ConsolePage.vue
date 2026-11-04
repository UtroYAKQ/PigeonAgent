<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    width?: 'default' | 'narrow'
  }>(),
  { width: 'default' },
)
</script>

<template>
  <div
    class="mx-auto w-full"
    :class="width === 'narrow' ? 'max-w-[1160px]' : 'max-w-[1360px]'"
  >
    <div class="px-4 pb-16 pt-4 sm:px-6">
      <header class="sticky top-0 z-20 flex flex-col gap-2 bg-background py-3 md:flex-row md:items-end md:justify-between">
        <div class="min-w-0">
          <h1 class="text-2xl font-bold leading-tight">{{ title }}</h1>
          <p v-if="description" class="mt-1 max-w-[78ch] text-sm leading-6 text-muted-foreground">
            {{ description }}
          </p>
        </div>
        <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2 md:justify-end">
          <slot name="actions" />
        </div>
      </header>

      <div class="pt-1">
        <slot />
      </div>
    </div>
  </div>
</template>
