<script setup lang="ts">
import { computed } from "vue";

import { fieldsOf, type FieldValues } from "../tools/schemaForm";
import type { ToolPayload } from "../tools";

/** 答题组件共用这一组 props：生成式表单用不到 item，但面板统一传。 */
const props = defineProps<{
  parameters: Record<string, unknown>;
  modelValue: unknown;
  item?: ToolPayload;
}>();

/** 答题组件的共用契约；生成式表单从不交卷，由底栏的提交决定。 */
const emit = defineEmits<{
  (event: "update:modelValue", value: unknown): void;
  (event: "commit"): void;
}>();

const fields = computed(() => fieldsOf(props.parameters));
const text = computed(() => (typeof props.modelValue === "string" ? props.modelValue : ""));
const values = computed<FieldValues>(() =>
  typeof props.modelValue === "object" && props.modelValue !== null
    ? (props.modelValue as FieldValues)
    : {},
);

function fieldValue(fieldKey: string): string {
  const value = values.value[fieldKey];
  return value == null ? "" : String(value);
}

function write(key: string, value: string | number | boolean): void {
  emit("update:modelValue", { ...values.value, [key]: value });
}
</script>

<template>
  <textarea
    v-if="fields.length === 0"
    :value="text"
    rows="2"
    placeholder="填写这个调用返回的内容"
    class="mt-2.5 w-full resize-y rounded-control border border-hair bg-canvas px-2.5 py-2 text-meta leading-relaxed outline-none focus:border-accent/50"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
  <div v-else class="mt-2.5 space-y-2">
    <label v-for="field in fields" :key="field.key" class="block">
      <span class="mb-1 flex items-center gap-1.5 text-micro text-faint">
        {{ field.label }}
        <span v-if="field.required" class="rounded-full bg-hover px-1.5 py-0.5">必填</span>
      </span>
      <select
        v-if="field.type === 'select'"
        :value="fieldValue(field.key)"
        class="w-full rounded-control border border-hair bg-canvas px-2.5 py-2 text-meta outline-none focus:border-accent/50"
        @change="write(field.key, ($event.target as HTMLSelectElement).value)"
      >
        <option value="">请选择</option>
        <option v-for="option in field.options" :key="option" :value="option">
          {{ option }}
        </option>
      </select>
      <button
        v-else-if="field.type === 'boolean'"
        type="button"
        :class="[
          'rounded-control border px-3 py-1.5 text-meta transition-colors',
          values[field.key]
            ? 'border-ink bg-ink text-canvas'
            : 'border-hair text-muted hover:bg-hover',
        ]"
        @click="write(field.key, !values[field.key])"
      >
        {{ values[field.key] ? "是" : "否" }}
      </button>
      <input
        v-else-if="field.type === 'number'"
        type="number"
        :value="fieldValue(field.key)"
        class="w-full rounded-control border border-hair bg-canvas px-2.5 py-2 text-meta outline-none focus:border-accent/50"
        @input="write(field.key, Number(($event.target as HTMLInputElement).value))"
      />
      <textarea
        v-else-if="field.type === 'textarea'"
        rows="3"
        :value="fieldValue(field.key)"
        class="w-full resize-y rounded-control border border-hair bg-canvas px-2.5 py-2 font-mono text-meta leading-relaxed outline-none focus:border-accent/50"
        @input="write(field.key, ($event.target as HTMLTextAreaElement).value)"
      />
      <input
        v-else
        type="text"
        :value="fieldValue(field.key)"
        class="w-full rounded-control border border-hair bg-canvas px-2.5 py-2 text-meta outline-none focus:border-accent/50"
        @input="write(field.key, ($event.target as HTMLInputElement).value)"
      />
    </label>
  </div>
</template>
