<script setup lang="ts">
import { computed } from "vue";

import { codeHtml, displayValue, kindOf, languageOf, overrideOf, type FieldKind } from "../render/infer";

const props = defineProps<{ tool: string; values: Record<string, unknown> }>();

interface Row {
  key: string;
  text: string;
  kind: FieldKind;
  html: string;
}

const rows = computed<Row[]>(() =>
  Object.entries(props.values).flatMap(([key, value]) => {
    const kind = overrideOf(props.tool, key).kind ?? kindOf(value);
    if (kind === "hidden") return [];
    const text = displayValue(value);
    if (kind !== "code" || !text.trim()) return [{ key, text, kind, html: "" }];
    const html = codeHtml(text, languageOf(props.tool, key, value, props.values));
    return [{ key, text, kind, html }];
  }),
);
</script>

<template>
  <div v-if="rows.length" class="mt-2.5 space-y-2">
    <div
      v-for="row in rows"
      :key="row.key"
      :class="row.kind === 'kv' ? 'flex items-baseline gap-3' : ''"
    >
      <template v-if="row.kind === 'kv'">
        <span class="w-20 shrink-0 truncate text-micro text-faint">{{ row.key }}</span>
        <span class="min-w-0 flex-1 truncate font-mono text-meta text-ink" :title="row.text">
          {{ row.text }}
        </span>
      </template>
      <div v-else class="min-w-0">
        <div class="mb-1 text-micro text-faint">{{ row.key }}</div>
        <pre
          v-if="row.html"
          class="code-box max-h-72 overflow-y-auto text-muted"
          v-html="row.html"
        ></pre>
        <pre v-else class="code-box max-h-72 overflow-y-auto whitespace-pre-wrap text-muted">{{
          row.text
        }}</pre>
      </div>
    </div>
  </div>
</template>
