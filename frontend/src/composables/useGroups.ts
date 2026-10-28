import { computed, ref } from "vue";

import {
  createGroup,
  deleteGroup,
  listGroups,
  renameGroup,
  updateSession,
} from "../lib/api";
import { reportError } from "../lib/toast";
import type { Session, SessionGroup } from "../types";

/** 折叠状态属于视图偏好，只留在本地，不进库。 */
const COLLAPSE_KEY = "pigeon.collapsedGroups";

function readCollapsed(): Set<number> {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((id): id is number => typeof id === "number") : []);
  } catch {
    return new Set();
  }
}

export function useGroups() {
  const groups = ref<SessionGroup[]>([]);
  const collapsed = ref<Set<number>>(readCollapsed());

  const sorted = computed(() => [...groups.value].sort((a, b) => a.sort_order - b.sort_order));

  async function refresh(): Promise<void> {
    try {
      groups.value = (await listGroups()).items;
    } catch (cause) {
      reportError(cause);
    }
  }

  function persistCollapsed(): void {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsed.value]));
  }

  function toggle(groupId: number): void {
    const next = new Set(collapsed.value);
    if (next.has(groupId)) next.delete(groupId);
    else next.add(groupId);
    collapsed.value = next;
    persistCollapsed();
  }

  async function create(name: string): Promise<SessionGroup | null> {
    const trimmed = name.trim();
    if (!trimmed) return null;
    try {
      const created = await createGroup(trimmed);
      groups.value = [...groups.value, created];
      return created;
    } catch (cause) {
      reportError(cause);
      return null;
    }
  }

  async function rename(groupId: number, name: string): Promise<void> {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const updated = await renameGroup(groupId, trimmed);
      groups.value = groups.value.map((group) => (group.id === groupId ? updated : group));
    } catch (cause) {
      reportError(cause);
    }
  }

  /** 删组只把会话放回未分组，会话本身不动。 */
  async function remove(groupId: number): Promise<void> {
    try {
      await deleteGroup(groupId);
      groups.value = groups.value.filter((group) => group.id !== groupId);
    } catch (cause) {
      reportError(cause);
    }
  }

  async function moveTo(session: Session, groupId: number | null): Promise<void> {
    try {
      Object.assign(session, await updateSession(session.id, { group_id: groupId }));
    } catch (cause) {
      reportError(cause);
    }
  }

  /** 退出登录/换账号：分组按账号隔离，清空；折叠偏好是本地视图设置，保留。 */
  function reset(): void {
    groups.value = [];
  }

  return { groups: sorted, collapsed, refresh, toggle, create, rename, remove, moveTo, reset };
}
