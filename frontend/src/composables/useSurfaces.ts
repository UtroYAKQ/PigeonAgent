import { computed, ref } from "vue";

export interface Surface {
  id: string;
  /** 同一个来源（通常是 tool_call_id）重复执行时替换而不是再开一页。 */
  key: string;
  /** html 当页面渲染，code 当源码读；body 分别是标记和纯文本。 */
  kind: "html" | "code";
  title: string;
  body: string;
  lang?: string;
}

const stack = ref<Surface[]>([]);
const activeId = ref<string | null>(null);
// auto 工具可能在同一批里连开多个预览，时间戳会撞，用自增序号
let seq = 0;

/** 弹层收在一个栈里，工具只负责 push；不然每个 handler 都会自己造一个弹窗。 */
export function useSurfaces() {
  const active = computed(
    () => stack.value.find((surface) => surface.id === activeId.value) ?? null,
  );

  function open(surface: Omit<Surface, "id">): string {
    const existing = stack.value.find((item) => item.key === surface.key);
    if (existing) {
      stack.value = stack.value.map((item) => (item === existing ? { ...item, ...surface } : item));
      activeId.value = existing.id;
      return existing.id;
    }
    const id = `${surface.kind}-${++seq}`;
    stack.value = [...stack.value, { ...surface, id }];
    activeId.value = id;
    return id;
  }

  function activate(id: string): void {
    activeId.value = id;
  }

  function close(id: string): void {
    const rest = stack.value.filter((surface) => surface.id !== id);
    stack.value = rest;
    if (activeId.value === id) activeId.value = rest[rest.length - 1]?.id ?? null;
  }

  /** 预览属于某个会话，切会话时整栈清掉，不然会攒出一排别的会话的 tab。 */
  function clear(): void {
    stack.value = [];
    activeId.value = null;
  }

  return { stack, active, open, activate, close, clear };
}
