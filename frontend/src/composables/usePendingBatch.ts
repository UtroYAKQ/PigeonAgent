import { reactive } from "vue";

import { resolveHandler, runAutoOnce } from "../tools";
import type { ToolPayload } from "../tools";
import type { InterruptView } from "../types";

/**
 * 待处理批次的会话状态：审批结论、填写的值、收掉的卡、提问页码、提交中。
 * 面板只是这份状态的视图——组件重挂载、resume 失败都不能把用户填过的东西弄丢。
 */
interface PendingState {
  approvals: Record<string, boolean | null>;
  values: Record<string, unknown>;
  settled: Record<string, true>;
  pages: Record<string, number>;
  submitting: Record<string, true>;
  seeded: Record<string, true>;
}

const state = reactive<PendingState>({
  approvals: {},
  values: {},
  settled: {},
  pages: {},
  submitting: {},
  seeded: {},
});

export function pendingPayload(item: InterruptView): ToolPayload {
  return { key: item.tool_call_id, name: item.name, argsParsed: item.argsParsed };
}

/** 把已经不在当前批次里的键清掉，状态不跟着会话无限长。 */
function prune(liveCalls: Set<string>, liveBatches: Set<string>): void {
  for (const key of Object.keys(state.approvals)) {
    if (!liveCalls.has(key)) delete state.approvals[key];
  }
  for (const key of Object.keys(state.values)) {
    if (!liveCalls.has(key)) delete state.values[key];
  }
  for (const key of Object.keys(state.settled)) {
    if (!liveCalls.has(key)) delete state.settled[key];
  }
  for (const key of Object.keys(state.pages)) {
    if (!liveCalls.has(key)) delete state.pages[key];
  }
  for (const key of Object.keys(state.seeded)) {
    if (!liveCalls.has(key)) delete state.seeded[key];
  }
  for (const key of Object.keys(state.submitting)) {
    if (!liveBatches.has(key)) delete state.submitting[key];
  }
}

export function usePendingBatch() {
  function init(items: InterruptView[]): void {
    prune(
      new Set(items.map((item) => item.tool_call_id)),
      new Set(items.map((item) => item.interrupt_id)),
    );
    for (const item of items) {
      if (item.kind === "approval" && state.approvals[item.tool_call_id] === undefined) {
        state.approvals[item.tool_call_id] = null;
      }
      if (item.kind !== "call" || state.seeded[item.tool_call_id]) continue;
      const handler = resolveHandler(item.name);
      // auto 项在浏览器里执行一次就够，结果由 registry 缓存，重挂载不重跑
      state.values[item.tool_call_id] =
        handler.execute === "auto" ? runAutoOnce(pendingPayload(item)) : "";
      state.seeded[item.tool_call_id] = true;
    }
  }

  return {
    init,
    approvalOf: (key: string): boolean | null | undefined => state.approvals[key],
    setApproval: (key: string, value: boolean): void => {
      state.approvals[key] = value;
    },
    valueOf: (key: string): unknown => state.values[key],
    setValue: (key: string, value: unknown): void => {
      state.values[key] = value;
    },
    pageOf: (key: string): number => state.pages[key] ?? 0,
    setPage: (key: string, index: number): void => {
      state.pages[key] = index;
    },
    isSettled: (key: string): boolean => state.settled[key] === true,
    settle: (key: string): void => {
      state.settled[key] = true;
    },
    submittingOf: (interruptId: string): boolean => state.submitting[interruptId] === true,
    /** 认领一次提交；已经在交或交过就返回 false。 */
    beginSubmit(interruptId: string): boolean {
      if (state.submitting[interruptId]) return false;
      state.submitting[interruptId] = true;
      return true;
    },
    /** 提交失败（网络 / 422 / 409）时放开，用户可以带着原答案重试。 */
    endSubmit(interruptId: string): void {
      delete state.submitting[interruptId];
    },
    /** 提交失败后把这一批的「已收掉」撤回：从第一张卡开始，答案都还在，重新确认即可。 */
    reopen(items: InterruptView[]): void {
      for (const item of items) delete state.settled[item.tool_call_id];
    },
  };
}
