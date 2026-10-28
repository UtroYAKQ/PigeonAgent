import PreviewToolCard from "../components/PreviewToolCard.vue";
import { useSurfaces } from "../composables/useSurfaces";
import type { AutoTool, ToolPayload } from "./registry";

function previewOf(item: ToolPayload): { key: string; title: string; html: string } {
  const args = (item.argsParsed ?? {}) as Record<string, unknown>;
  return {
    key: item.key,
    title: String(args.title ?? "预览"),
    html: String(args.html ?? ""),
  };
}

/** 同一个 tool call 重复打开只替换那一页，不会攒出新 tab。 */
function show(item: ToolPayload): boolean {
  const { key, title, html } = previewOf(item);
  if (!html.trim()) return false;
  useSurfaces().open({ key, kind: "html", title, body: html });
  return true;
}

export const openHtmlPreview: AutoTool = {
  name: "ui_open_html_preview",
  description:
    "把一段完整 HTML 交给浏览器渲染，在聊天页右侧展开预览。需要在对话外展示页面、图表或排版效果时调用。",
  parameters: {
    type: "object",
    properties: {
      title: { type: "string", description: "预览标题，显示在面板头部" },
      html: { type: "string", description: "完整 HTML 片段，可含内联 style/script" },
    },
    required: ["html"],
  },
  execute: "auto",
  card: PreviewToolCard,
  reopenLabel: "打开预览",
  run: (item) => (show(item) ? "预览已在右侧打开。" : "没有可预览的内容。"),
  reopen: (item) => {
    show(item);
  },
};
