<script setup lang="ts">
import { Download, FileText } from "lucide-vue-next";
import { ref } from "vue";

import { downloadFile } from "../lib/auth";
import { errorMessage } from "../lib/errors";
import { pushToast } from "../lib/toast";

const props = defineProps<{
  storageKey: string;
  name: string;
  size?: number | null;
}>();

const downloading = ref(false);

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

async function download(): Promise<void> {
  if (downloading.value) return;
  downloading.value = true;
  try {
    await downloadFile(props.storageKey, props.name);
  } catch (cause) {
    pushToast(`下载 ${props.name} 失败：${errorMessage(cause)}`);
  } finally {
    downloading.value = false;
  }
}
</script>

<template>
  <button
    class="group flex max-w-full items-center gap-2 rounded-surface border border-hair bg-surface px-3 py-2 text-left text-ui transition-colors hover:border-accent/50 hover:bg-hover disabled:opacity-60"
    :title="`下载 ${name}`"
    :disabled="downloading"
    @click="download"
  >
    <FileText :size="16" :stroke-width="1.7" class="shrink-0 text-muted" />
    <span class="min-w-0 truncate text-ink group-hover:text-accent">{{ name }}</span>
    <span v-if="size" class="num shrink-0 text-micro text-faint">{{ formatBytes(size) }}</span>
    <Download
      :size="14"
      :stroke-width="1.7"
      class="shrink-0 text-faint transition-colors group-hover:text-accent"
      :class="{ 'animate-spin': downloading }"
    />
  </button>
</template>
