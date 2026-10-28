<script setup lang="ts">
import { computed } from "vue";

import { copyText } from "../lib/clipboard";
import { renderMarkdown } from "../lib/markdown";
import { useSurfaces } from "../composables/useSurfaces";
import { downloadFile } from "../lib/auth";

const props = defineProps<{ text: string; caret?: boolean }>();
const html = computed(() => renderMarkdown(props.text));

/** 代码块没有 id，用内容做稳定 key：同一段再展开只替换那一页，不攒 tab。 */
function keyCode(code: string): string {
  let hash = 0;
  for (let i = 0; i < code.length; i += 1) hash = (hash * 31 + code.charCodeAt(i)) | 0;
  return `md-${(hash >>> 0).toString(36)}`;
}

/** 代码块是 v-html 出来的，展开和复制都走事件委托，不给每块绑。 */
async function onClick(event: MouseEvent): Promise<void> {
  const target = event.target as HTMLElement | null;
  const fileLink = target?.closest<HTMLElement>(".file-link");
  if (fileLink) {
    event.preventDefault();
    const fileId = fileLink.dataset.fileId;
    if (fileId) void downloadFile(fileId, fileLink.dataset.name ?? undefined);
    return;
  }
  const frame = target?.closest(".code-frame");
  if (!frame) return;
  const code = frame.querySelector("code")?.textContent ?? "";

  if (target?.closest(".code-expand")) {
    const lang = frame.querySelector(".code-lang")?.textContent ?? "";
    useSurfaces().open({
      key: keyCode(code),
      kind: "code",
      title: lang && lang !== "text" ? lang : "代码",
      body: code,
      lang,
    });
    return;
  }

  const button = target?.closest<HTMLButtonElement>(".code-copy");
  if (!button || button.dataset.busy) return;
  if (!(await copyText(code))) return;
  button.dataset.busy = "1";
  button.textContent = "已复制";
  window.setTimeout(() => {
    delete button.dataset.busy;
    button.textContent = "复制";
  }, 1400);
}
</script>

<template>
  <div :class="['prose-chat', caret ? 'caret' : '']" v-html="html" @click="onClick" />
</template>
