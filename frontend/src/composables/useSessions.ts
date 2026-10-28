import { ref } from "vue";

import { createSession, deleteSession, listSessions, updateSession } from "../lib/api";
import { reportError } from "../lib/toast";
import type { Session } from "../types";

export function useSessions() {
  const sessions = ref<Session[]>([]);

  async function refresh(): Promise<void> {
    try {
      sessions.value = (await listSessions()).items;
    } catch (cause) {
      reportError(cause);
    }
  }

  async function create(
    modelId: number | null,
    groupId: number | null = null,
  ): Promise<Session | null> {
    try {
      const created = await createSession(modelId, groupId);
      sessions.value = [created, ...sessions.value];
      return created;
    } catch (cause) {
      reportError(cause);
      return null;
    }
  }

  async function rename(sessionId: string, title: string): Promise<void> {
    try {
      const updated = await updateSession(sessionId, { title });
      const hit = sessions.value.find((session) => session.id === sessionId);
      if (hit) Object.assign(hit, updated);
    } catch (cause) {
      reportError(cause);
      await refresh();
    }
  }

  async function remove(sessionId: string): Promise<void> {
    try {
      await deleteSession(sessionId);
      sessions.value = sessions.value.filter((session) => session.id !== sessionId);
    } catch (cause) {
      reportError(cause);
    }
  }

  /** 退出登录/换账号：把列表清空，别把上一个账号的数据带到下一个。 */
  function reset(): void {
    sessions.value = [];
  }

  return { sessions, refresh, create, rename, remove, reset };
}
