<template>
  <div class="space-y-3">
    <div
      v-if="$slots.toolbar"
      class="flex flex-wrap items-center gap-2.5"
    >
      <slot name="toolbar" />
    </div>

    <div class="overflow-hidden rounded-lg border border-border bg-card">
      <slot />
    </div>

    <div
      v-if="$slots.footer"
      class="flex flex-wrap items-center justify-between gap-3 px-1"
    >
      <slot name="footer" />
    </div>
  </div>
</template>
