/** 工具参数/结果的展示形状。这里不认识任何工具名，只认数据形状。 */

import hljs from "highlight.js/lib/common";

export type FieldKind = "kv" | "code" | "hidden";

/** 覆盖表允许的键：只有这两个，出现函数或条件就是跑偏。 */
export interface FieldOverride {
  kind?: FieldKind;
  language?: string;
}

/**
 * 形状推断说不动时才进来（例如 html 字段推断不出语言）。
 * collapse 之类的键等真有消费者再加，别先占位。
 */
const DISPLAY: Record<string, Record<string, FieldOverride>> = {
  ui_open_html_preview: { html: { language: "html" } },
};

export function overrideOf(tool: string, key: string): FieldOverride {
  return DISPLAY[tool]?.[key] ?? {};
}

export function kindOf(value: unknown): FieldKind {
  if (value == null || value === "") return "hidden";
  if (typeof value === "object") return "code";
  const text = String(value);
  return text.includes("\n") || text.length > 80 ? "code" : "kv";
}

/** 同批参数里找一个像文件名的值，用它的后缀当高亮语言。 */
function extensionOf(values: Record<string, unknown>): string | null {
  for (const value of Object.values(values)) {
    if (typeof value !== "string") continue;
    const head = value.trim().split("\n", 1)[0] ?? "";
    const hit = /\.([a-z0-9]{1,8})$/i.exec(head);
    if (hit) return hit[1].toLowerCase();
  }
  return null;
}

export function languageOf(
  tool: string,
  key: string,
  value: unknown,
  siblings: Record<string, unknown>,
): string | null {
  const forced = overrideOf(tool, key).language;
  if (forced) return forced;
  if (typeof value === "object") return "json";
  const rest = Object.fromEntries(
    Object.entries(siblings).filter(([siblingKey]) => siblingKey !== key),
  );
  return extensionOf(rest);
}

/** 高亮失败或语言不认识时返回空串，调用方按纯文本渲染。 */
export function codeHtml(text: string, language: string | null): string {
  if (!language || !hljs.getLanguage(language)) return "";
  try {
    return hljs.highlight(text, { language }).value;
  } catch {
    return "";
  }
}

/** 待办卡的人话标题：只做 {参数} 占位替换，不许出现条件分支。 */
const HEADLINE: Record<string, string> = {
  publish_file: "发布 {path}",
  delete_file: "删除 {path}",
  delete_log: "删除 {path}",
  write_file: "写入 {path}",
  archive_log: "归档 {path}",
  ui_ask_user_question: "{question}",
};

function scalarOf(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

/** 值转展示文本：对象摊成缩进 JSON，标量原样，空值给空串由调用方决定占位。 */
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

export function headlineOf(tool: string, args: Record<string, unknown>): string {
  const template = HEADLINE[tool];
  if (template) {
    return template.replace(/\{(\w+)\}/g, (_, key: string) => scalarOf(args[key]) || `{${key}}`);
  }
  const first = Object.values(args).map(scalarOf).find(Boolean);
  return first ? `${tool} ${first}` : tool;
}
