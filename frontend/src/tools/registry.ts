import type { Component } from "vue";

import type { FrontendToolDeclaration } from "../types";
import { readyFor, resultFor } from "./schemaForm";

/** handler 需要的最小载荷；面板的待办项和消息流里的工具卡都能映射成它。 */
export interface ToolPayload {
  key: string;
  name: string;
  argsParsed: Record<string, unknown> | null;
}

interface ToolBase {
  name: string;
  description: string;
  /** JSON object schema；也是自动表单的依据。 */
  parameters: Record<string, unknown>;
  /** 历史卡的一行回显；不写就原样展示结果内容。 */
  formatResult?(value: unknown): string;
  /** 消息流里的卡片：不写 = 通用工具行，写了 = 该工具自己的长相（只吃 ToolItem）。 */
  card?: Component;
}

/** 挂上就执行、结果自动回填，不打断用户。 */
export interface AutoTool extends ToolBase {
  execute: "auto";
  run(item: ToolPayload): unknown;
  /** 历史里的工具卡给出的重开入口；不声明就没有按钮。 */
  reopen?(item: ToolPayload): void;
  reopenLabel?: string;
}

/** 需要人在面板里处理完，再随批次一起提交。 */
export interface ManualTool extends ToolBase {
  execute: "manual";
  /** 要不要带上 item：有的工具（提问）答没答完取决于参数里的题目。 */
  isReady(value: unknown, item: ToolPayload): boolean;
  toResult(value: unknown, item: ToolPayload): unknown;
  /** 不写 = 用 SchemaFields 按 parameters 生成表单；写了 = 该工具自带答题组件。 */
  form?: Component;
}

export type ToolHandler = AutoTool | ManualTool;

/** 只有参数、没有交互的工具：按 schema 自动生成表单。 */
export function manualTool(
  name: string,
  description: string,
  parameters: Record<string, unknown> = {},
): ManualTool {
  return {
    name,
    description,
    parameters,
    execute: "manual",
    isReady: (value) => readyFor(parameters, value),
    toResult: (value) => resultFor(parameters, value),
  };
}

const registry = new Map<string, ToolHandler>();
// 未注册工具的兜底 handler 要按名字复用，否则每次渲染换引用，输入框会掉焦点
const fallbacks = new Map<string, ManualTool>();
// 模块作用域：审批面板会因为 running 翻转而重挂载，副作用不能重来
const autoResults = new Map<string, unknown>();
/** 按 tool_call_id 只增不减，长会话要有个上限，丢最旧的。 */
const CACHE_LIMIT = 500;

function keepRecent<K, V>(map: Map<K, V>, key: K, value: V): void {
  map.set(key, value);
  if (map.size > CACHE_LIMIT) {
    const oldest = map.keys().next().value;
    if (oldest !== undefined) map.delete(oldest);
  }
}

export function registerTool(handler: ToolHandler): void {
  registry.set(handler.name, handler);
}

/** 只查已注册的：消息流里的普通工具卡不该拿到兜底 handler。 */
export function findHandler(name: string): ToolHandler | null {
  return registry.get(name) ?? null;
}

/** 没注册的工具退回手填文本框：加新工具不该改面板。 */
export function resolveHandler(name: string): ToolHandler {
  const registered = registry.get(name);
  if (registered) return registered;
  const fallback = fallbacks.get(name) ?? manualTool(name, "");
  fallbacks.set(name, fallback);
  return fallback;
}

/** 同一 tool call 只执行一次，重挂载后仍拿得到原结果。 */
export function runAutoOnce(item: ToolPayload): unknown {
  if (!autoResults.has(item.key)) {
    const handler = resolveHandler(item.name);
    keepRecent(autoResults, item.key, handler.execute === "auto" ? handler.run(item) : undefined);
  }
  return autoResults.get(item.key);
}

/** 每轮随请求上传；后端据此建外部 toolset，不需要为前端工具写服务端实现。 */
export function declaredTools(): FrontendToolDeclaration[] {
  return [...registry.values()].map(({ name, description, parameters }) => ({
    name,
    description,
    parameters,
  }));
}
