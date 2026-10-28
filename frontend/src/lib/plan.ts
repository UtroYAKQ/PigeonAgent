import type { DisplayBlock, ToolItem } from "../types";

export type PlanStatus = "pending" | "active" | "done";

export interface PlanStep {
  content: string;
  status: PlanStatus;
}

export interface PlanState {
  steps: PlanStep[];
  done: number;
  total: number;
}

const STATUSES = ["pending", "active", "done"] as const;

/** 后端的清单工具；正文不展示它们，状态只走输入框上方的浮窗。 */
const PLAN_TOOLS = new Set(["plan_set", "plan_show"]);

export function isPlanTool(name: string): boolean {
  return PLAN_TOOLS.has(name);
}

function isPlanItem(value: unknown): value is PlanStep {
  if (typeof value !== "object" || value === null) return false;
  const step = value as Record<string, unknown>;
  return (
    typeof step.content === "string" &&
    STATUSES.includes(step.status as PlanStatus)
  );
}

/** plan_set 的返回值就是清单本身；结果优先，读到空清单再回退到参数。 */
function fromResult(content: string): PlanState | null {
  let payload: unknown;
  try {
    payload = JSON.parse(content);
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null) return null;
  const items = (payload as Record<string, unknown>).items;
  if (!Array.isArray(items)) return null;
  const steps = items.filter(isPlanItem);
  return steps.length > 0 ? build(steps) : null;
}

/** 参数流式进来时清单已经能看了：items 一到齐就先按参数画。 */
function fromArgs(args: Record<string, unknown> | null): PlanState | null {
  if (!args) return null;
  const items = args.items;
  if (!Array.isArray(items) || items.length === 0) return null;
  const contents = items.filter((item): item is string => typeof item === "string");
  if (contents.length !== items.length) return null;
  const done = new Set(
    Array.isArray(args.done)
      ? args.done.filter((index): index is number => typeof index === "number")
      : [],
  );
  const active = typeof args.active === "number" ? args.active : -1;
  return build(
    contents.map((content, index) => ({
      content,
      status: done.has(index) ? "done" : index === active ? "active" : "pending",
    })),
  );
}

function build(steps: PlanStep[]): PlanState {
  return {
    steps,
    done: steps.filter((step) => step.status === "done").length,
    total: steps.length,
  };
}

function latestToolPlan(items: ToolItem[]): PlanState | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (!isPlanTool(item.name)) continue;
    const result = item.result ? fromResult(item.result.content) : null;
    const plan = result ?? fromArgs(item.argsParsed);
    if (plan) return plan;
  }
  return null;
}

/**
 * 本轮的清单：从最后一条回答往前找，遇到本轮的提问就停。
 * 中断续跑会另起一个 run，但和被打断的 run 同属一个回答块，所以清单不会在续跑时消失。
 */
export function planOf(blocks: DisplayBlock[]): PlanState | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    if (block.role === "user") return null;
    const tools = block.items.filter(
      (item): item is ToolItem => item.type === "tool",
    );
    const plan = latestToolPlan(tools);
    if (plan) return plan;
  }
  return null;
}
