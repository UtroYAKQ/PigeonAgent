<script setup lang="ts">
import { Check } from "lucide-vue-next";
import { computed, ref } from "vue";

import type { PlanState } from "../lib/plan";

const props = defineProps<{ plan: PlanState; running?: boolean }>();

const open = ref(false);
const done = computed(() => props.plan.done === props.plan.total);
/** 等用户处理卡片时这轮并没有在跑，胶囊不能一直转圈。 */
const active = computed(() => props.running === true);
</script>

<template>
  <div data-plan-dock class="flex w-full flex-col items-center gap-2">
    <ol
      v-if="open"
      class="float rise max-h-52 w-fit max-w-[30rem] overflow-y-auto px-4 py-3"
    >
      <li
        v-for="(step, index) in plan.steps"
        :key="`${index}:${step.content}`"
        class="flex min-w-0 gap-2.5"
      >
        <span class="flex w-3.5 shrink-0 flex-col items-center">
          <span class="mt-[3px] grid size-3.5 place-items-center">
            <Check
              v-if="step.status === 'done'"
              :size="12"
              :stroke-width="2.2"
              class="text-faint"
            />
            <span v-else-if="step.status === 'active'" class="size-2 rounded-full bg-accent" />
            <span v-else class="size-2 rounded-full border border-faint/50" />
          </span>
          <span
            v-if="index < plan.steps.length - 1"
            class="mt-1 w-px flex-1 bg-faint/25"
          />
        </span>
        <span
          :class="[
            'min-w-0 text-ui leading-5',
            index < plan.steps.length - 1 ? 'pb-2' : '',
            step.status === 'active'
              ? 'text-ink'
              : step.status === 'done'
                ? 'text-faint'
                : 'text-muted',
          ]"
        >
          {{ step.content }}
        </span>
      </li>
    </ol>

    <button
      type="button"
      class="float flex items-center gap-1.5 px-3 py-1.5"
      :aria-expanded="open"
      @click="open = !open"
    >
      <Check v-if="done" :size="13" :stroke-width="2.2" class="text-muted" />
      <span
        v-else-if="active"
        class="size-3 animate-spin rounded-full border border-hair border-t-faint"
      />
      <span v-else class="size-1.5 rounded-full bg-accent" />
      <span class="num text-meta text-muted">
        步骤 {{ plan.done }}/{{ plan.total }}
      </span>
    </button>
  </div>
</template>
