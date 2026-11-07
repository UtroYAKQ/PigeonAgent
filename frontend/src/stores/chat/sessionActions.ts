import type { ComputedRef, Ref } from 'vue'

import { groupsApi, sessionsApi } from '@/api/sessions'
import type { ChatSession, LlmModel, SessionGroup, ThinkingLevel, UUID } from '@/types/api'

export interface SessionActionDeps {
  busy: ComputedRef<boolean>
  currentSessionId: Ref<UUID | null>
  currentSession: Ref<ChatSession | null>
  currentThinkingLevel: ComputedRef<ThinkingLevel | null>
  thinkingLevels: ComputedRef<ThinkingLevel[]>
  models: Ref<LlmModel[]>
  sessions: Ref<ChatSession[]>
  archivedSessions: Ref<ChatSession[]>
  groups: Ref<SessionGroup[]>
  pendingModelId: Ref<number | null>
  pendingThinkingLevel: Ref<ThinkingLevel | null>
  updateSessionInLists: (session: ChatSession) => void
  removeSessionFromLists: (id: UUID) => void
  resetCurrent: () => void
  refreshSessions: () => Promise<void>
}

export function createSessionActions(deps: SessionActionDeps) {
  const {
    busy,
    currentSessionId,
    currentSession,
    currentThinkingLevel,
    thinkingLevels,
    models,
    sessions,
    archivedSessions,
    groups,
    pendingModelId,
    pendingThinkingLevel,
    updateSessionInLists,
    removeSessionFromLists,
    resetCurrent,
    refreshSessions,
  } = deps

  async function renameSession(session: ChatSession, title: string): Promise<void> {
    const updated = await sessionsApi.update(session.id, {
      title: title.trim(),
    })
    updateSessionInLists(updated)
  }

  async function updateSessionModel(modelId: number): Promise<void> {
    if (busy.value) return
    const nextModel = models.value.find(model => model.id === modelId)
    const level =
      currentThinkingLevel.value && nextModel?.thinking_levels.includes(currentThinkingLevel.value)
        ? currentThinkingLevel.value
        : null
    if (!currentSession.value) {
      pendingModelId.value = modelId
      pendingThinkingLevel.value = level
      return
    }
    const updated = await sessionsApi.update(currentSession.value.id, {
      model_id: modelId,
      thinking_level: level,
    })
    updateSessionInLists(updated)
    pendingModelId.value = modelId
    pendingThinkingLevel.value = level
  }

  async function setThinkingLevel(level: ThinkingLevel | null): Promise<void> {
    if (level && !thinkingLevels.value.includes(level)) return
    if (!currentSession.value) {
      pendingThinkingLevel.value = level
      return
    }
    const updated = await sessionsApi.update(currentSession.value.id, {
      thinking_level: level,
    })
    updateSessionInLists(updated)
    pendingThinkingLevel.value = level
  }

  async function markSessionRead(sessionId: UUID): Promise<void> {
    try {
      const updated = await sessionsApi.markRead(sessionId)
      updateSessionInLists(updated)
    } catch (error) {
      // 已读是轻量状态，失败不影响对话，但侧栏的红点没清掉要能被查出来
      console.warn('标记会话已读失败', error)
    }
  }

  async function archiveSession(session: ChatSession): Promise<void> {
    if (busy.value && session.id === currentSessionId.value) return
    const updated = await sessionsApi.update(session.id, {
      status: 'archived',
    })
    sessions.value = sessions.value.filter(item => item.id !== session.id)
    archivedSessions.value = [
      updated,
      ...archivedSessions.value.filter(item => item.id !== session.id),
    ]
    if (currentSessionId.value === session.id) resetCurrent()
  }

  async function unarchiveSession(session: ChatSession): Promise<void> {
    const updated = await sessionsApi.update(session.id, { status: 'active' })
    archivedSessions.value = archivedSessions.value.filter(item => item.id !== session.id)
    sessions.value = [updated, ...sessions.value.filter(item => item.id !== session.id)]
  }

  async function deleteSession(session: ChatSession): Promise<void> {
    await sessionsApi.remove(session.id)
    removeSessionFromLists(session.id)
  }

  async function moveSessionToGroup(session: ChatSession, groupId: number | null): Promise<void> {
    const updated = await sessionsApi.update(session.id, { group_id: groupId })
    updateSessionInLists(updated)
    void refreshSessions().catch(() => undefined)
  }

  async function createGroup(name: string): Promise<SessionGroup> {
    const group = await groupsApi.create(name)
    groups.value = [...groups.value, group]
    return group
  }

  async function renameGroup(group: SessionGroup, name: string): Promise<void> {
    const updated = await groupsApi.rename(group.id, name)
    groups.value = groups.value.map(item => (item.id === updated.id ? updated : item))
  }

  async function deleteGroup(group: SessionGroup): Promise<void> {
    await groupsApi.remove(group.id)
    groups.value = groups.value.filter(item => item.id !== group.id)
    await refreshSessions()
  }

  return {
    renameSession,
    updateSessionModel,
    setThinkingLevel,
    markSessionRead,
    archiveSession,
    unarchiveSession,
    deleteSession,
    moveSessionToGroup,
    createGroup,
    renameGroup,
    deleteGroup,
  }
}
