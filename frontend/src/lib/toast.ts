import { ref } from "vue";

import { errorMessage } from "./errors";

export type ToastKind = "error" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

/** 页面顶部消息条：只收对话正文之外的操作错误，聊天里的错误仍留在气泡上。 */
export const toasts = ref<Toast[]>([]);

const LIFETIME: Record<ToastKind, number> = { error: 6000, info: 4000 };
const MAX_VISIBLE = 3;
let nextId = 1;
const timers = new Map<number, number>();
let host: HTMLElement | null = null;

/** 消息条住在 popover 里：top layer 只会往栈顶叠，模态窗口后开就会盖住它。 */
function stackTopLayer(): void {
  if (!host?.showPopover) return;
  const open = host.matches(":popover-open");
  if (toasts.value.length === 0) {
    if (open) host.hidePopover();
    return;
  }
  if (open) host.hidePopover();
  host.showPopover();
}

export function bindToastHost(element: HTMLElement | null): void {
  host = element;
  stackTopLayer();
}

/** 模态窗口 showModal 之后调用：把已显示的消息条重新放回栈顶。 */
export function raiseToasts(): void {
  stackTopLayer();
}

export function dismissToast(id: number): void {
  const timer = timers.get(id);
  if (timer != null) window.clearTimeout(timer);
  timers.delete(id);
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
  stackTopLayer();
}

function schedule(toast: Toast): void {
  const timer = timers.get(toast.id);
  if (timer != null) window.clearTimeout(timer);
  timers.set(
    toast.id,
    window.setTimeout(() => dismissToast(toast.id), LIFETIME[toast.kind]),
  );
}

export function pushToast(message: string, kind: ToastKind = "error"): void {
  const text = message.trim();
  if (!text) return;
  // 同一句话反复报（比如连续几次自动刷新失败）只保留一条，重新计时
  const existing = toasts.value.find((toast) => toast.message === text && toast.kind === kind);
  if (existing) {
    stackTopLayer();
    schedule(existing);
    return;
  }
  const toast: Toast = { id: nextId++, kind, message: text };
  toasts.value = [...toasts.value, toast].slice(-MAX_VISIBLE);
  stackTopLayer();
  schedule(toast);
}

/** 接口/操作失败统一从这里报：顶部一条消息，不打断当前操作。 */
export function reportError(cause: unknown): void {
  pushToast(errorMessage(cause));
}
