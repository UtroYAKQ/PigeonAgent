import type { InterruptKind } from "../types";

/** 消息流里工具卡的四种类别：颜色和图标都从这张表来，别再各写一份。 */
export type ToolKind = "approval" | "call" | "ask" | "tool";

export function kindOf(kind: InterruptKind | null | undefined): ToolKind {
  if (kind === "approval") return "approval";
  if (kind === "call") return "call";
  return "tool";
}

/** 颜色只跟类别走，不跟状态走；状态交给行首文字。 */
export const KIND_TILE: Record<ToolKind, string> = {
  approval: "bg-warn/10 text-warn",
  call: "bg-ok/10 text-ok",
  ask: "bg-accent-soft text-accent",
  tool: "bg-hover text-muted",
};
