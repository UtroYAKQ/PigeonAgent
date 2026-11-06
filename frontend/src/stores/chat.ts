import { computed, ref, shallowRef } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { defineStore } from 'pinia'

import { capabilitiesApi } from '@/api/capabilities'
import { groupsApi, sessionsApi } from '@/api/sessions'
import { modelsApi } from '@/api/models'
import { runsApi } from '@/api/runs'
import { errorMessage, toApiError } from '@/lib/http'
import { fileTitleFromContent } from '@/lib/format'
import { FRONTEND_TOOLS } from '@/lib/frontendTools'
import { buildPendingBatches } from '@/lib/pending'
import { requestScroll } from '@/lib/scrollIntent'
import { applyAgUiEvent } from '@/lib/agui'
import { StreamGoneError, streamRun } from '@/lib/sse'
import { usePanelStore } from '@/stores/panel'
import type {
  AgUiEvent,
  Capabilities,
  ChatSession,
  DraftAttachment,
  LiveRun,
  LlmModel,
  RunCreatePayload,
  SessionGroup,
  SessionRun,
  ThinkingLevel,
  ToolResultItem,
  UUID,
} from '@/types/api'

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const SESSION_PAGE_SIZE = 50
const SEARCH_PAGE_SIZE = 50
// 打开会话先取最近这么多条 run 渲染历史；开轮后的刷新与超时收尾各自要的窗口不同。
// 手机首屏少渲染一些历史，"加载更早"随时补得回来。
const RUNS_PAGE_SIZE = 40
const RUNS_PAGE_SIZE_COMPACT = 24
const RUNS_REFRESH_PAGE_SIZE = 60
const RUNS_REFRESH_PAGE_SIZE_COMPACT = 32
const RUNS_SETTLE_PAGE_SIZE = 80
const RUNS_SETTLE_PAGE_SIZE_COMPACT = 40

function runsPageSize(full: number, compact: number): number {
  if (typeof window === 'undefined') return full
  return window.matchMedia('(max-width: 767px)').matches ? compact : full
}
// 事件流断了也要确认后端真的结束：首轮快查，之后指数退避，总时长封顶
const SETTLE_FIRST_DELAY_MS = 180
const SETTLE_MAX_DELAY_MS = 15_000
const SETTLE_TIMEOUT_MS = 5 * 60_000

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export interface SendMessageInput {
  text: string
  attachments?: DraftAttachment[]
  parentRunId?: UUID | null
  retryRunId?: UUID
  groupId?: number | null
}

export interface SendMessageOutcome {
  sessionId: UUID
  /**
   * 撞上别的标签页正在跑的回复时为 true：已接入那条流观看，
   * 输入框的文本保留，这轮结束后用户可以直接再发。
   */
  joinedActiveRun: boolean
}

export const useChatStore = defineStore('chat', () => {
  const panels = usePanelStore()
  const models = ref<LlmModel[]>([])
  const modelsLoaded = ref(false)
  const groups = ref<SessionGroup[]>([])
  const sessions = ref<ChatSession[]>([])
  const archivedSessions = ref<ChatSession[]>([])
  const sessionsHasMore = ref(false)
  const archivedHasMore = ref(false)
  const loadingMoreSessions = ref(false)
  const loadingMoreArchived = ref(false)
  const searchQuery = ref('')
  const searchResults = ref<ChatSession[]>([])
  const searching = ref(false)
  let searchGeneration = 0
  const sessionsLoaded = ref(false)
  const bootstrapping = ref(false)
  const bootstrapError = ref<string | null>(null)

  const currentSessionId = ref<UUID | null>(null)
  const currentSession = ref<ChatSession | null>(null)
  const runs = ref<SessionRun[]>([])
  const runsHasMore = ref(false)
  const loadingSession = ref(false)
  const loadingEarlier = ref(false)
  const sessionError = ref<string | null>(null)

  const activeRunId = ref<string | null>(null)
  const liveRun = ref<LiveRun | null>(null)
  // 同一 run 续写时，live 流只包含续写段；视图需要先铺上这条 run 已落库的内容
  const resumedLiveRunId = ref<string | null>(null)
  const cancelling = ref(false)
  const streamAbort = shallowRef<AbortController | null>(null)
  let streamGeneration = 0

  const pendingModelId = ref<number | null>(null)
  const pendingThinkingLevel = ref<ThinkingLevel | null>(null)
  const capabilities = ref<Capabilities | null>(null)
  const webSearchEnabled = useLocalStorage('pigeon.web-search', false)
  // 图片默认开着：模型自主决定画不画，用户多数时候不需要每次手动打开
  const imageGenerationEnabled = useLocalStorage('pigeon.image-generation', true)
  // 用户选过的图片模型；模型下架后自动回落到能力接口给的默认值
  const imageModelId = useLocalStorage<number | null>('pigeon.image-model', null)
  const resumingInterruptId = ref<string | null>(null)
  // 已经成功提交过的中断批次。卡片该不该消失原本只看工具结果有没有落到快照里，
  // 而开轮后的列表刷新失败时只 console.warn，批次会永远停在「未决」并把输入框锁死。
  const resumedInterruptIds = ref<string[]>([])
  const editingRun = ref<SessionRun | null>(null)
  const editingText = ref('')

  const activeModels = computed(() => models.value.filter(model => model.is_active))
  const defaultModel = computed(
    () => activeModels.value.find(model => model.is_default) ?? activeModels.value[0] ?? null,
  )
  const currentModelId = computed(
    () => currentSession.value?.model_id ?? pendingModelId.value ?? defaultModel.value?.id ?? null,
  )
  const currentModel = computed(
    () => models.value.find(model => model.id === currentModelId.value) ?? null,
  )
  const thinkingLevels = computed(() => currentModel.value?.thinking_levels ?? [])
  const currentThinkingLevel = computed<ThinkingLevel | null>(() => {
    const level = currentSession.value?.thinking_level ?? pendingThinkingLevel.value
    return level && thinkingLevels.value.includes(level) ? level : null
  })
  const busy = computed(() => activeRunId.value !== null)
  const isStreaming = computed(() => Boolean(liveRun.value && !liveRun.value.finished))
  const hasMessages = computed(() => runs.value.length > 0 || Boolean(liveRun.value))
  const webSearchAvailable = computed(
    () => Boolean(capabilities.value?.web_search) && currentModel.value?.supports_tools !== false,
  )
  const effectiveWebSearch = computed(() => webSearchEnabled.value && webSearchAvailable.value)
  const imageModels = computed(() => capabilities.value?.image_models ?? [])
  const currentImageModel = computed(() => {
    const selected = imageModels.value.find(model => model.id === imageModelId.value)
    if (selected) return selected
    const fallbackId = capabilities.value?.default_image_model_id
    return imageModels.value.find(model => model.id === fallbackId) ?? imageModels.value[0] ?? null
  })
  const imageGenerationAvailable = computed(
    () =>
      Boolean(capabilities.value?.image_generation)
      && imageModels.value.length > 0
      && currentModel.value?.supports_tools !== false,
  )
  const effectiveImageGeneration = computed(
    () =>
      imageGenerationEnabled.value
      && imageGenerationAvailable.value
      && currentImageModel.value !== null,
  )
  // 能力还没取到（或取失败）时用的兜底值；以后端 app/core/config.py 与
  // app/schemas/run.py 的 MAX_ATTACHMENTS / MAX_RESOURCES 为准，改动要同步这里
  const maxUploadBytes = computed(() => capabilities.value?.max_upload_bytes ?? 20 * 1024 * 1024)
  const maxImageAttachments = computed(() => capabilities.value?.max_image_attachments ?? 5)
  const maxResourceFiles = computed(() => capabilities.value?.max_resource_files ?? 10)
  const toolResultsByCallId = computed(() => {
    const results = new Map<string, ToolResultItem>()
    for (const run of runs.value) {
      for (const item of run.content) {
        if (item.type === 'tool_result') results.set(item.tool_call_id, item)
      }
    }
    return results
  })
  const hasPendingInterrupts = computed(() => {
    const results = toolResultsByCallId.value
    return runs.value.some(run =>
      buildPendingBatches(run, results).some(
        batch => !batch.resolved && !resumedInterruptIds.value.includes(batch.interruptId),
      ),
    )
  })

  function updateSessionInLists(session: ChatSession): void {
    const replace = (list: ChatSession[]) =>
      list.map(item => (item.id === session.id ? session : item))
    sessions.value = replace(sessions.value)
    archivedSessions.value = replace(archivedSessions.value)
    searchResults.value = replace(searchResults.value)
    if (currentSessionId.value === session.id) {
      currentSession.value = session
    }
  }

  function removeSessionFromLists(id: UUID): void {
    sessions.value = sessions.value.filter(item => item.id !== id)
    archivedSessions.value = archivedSessions.value.filter(item => item.id !== id)
    searchResults.value = searchResults.value.filter(item => item.id !== id)
    panels.closeTabs(id)
    if (currentSessionId.value === id) {
      resetCurrent()
    }
  }

  /** 换会话或清空会话都要先收掉的运行态：流、编辑态、待恢复的确认、历史列表。 */
  function clearTurnState(): void {
    abortActiveStream()
    editingRun.value = null
    editingText.value = ''
    resumingInterruptId.value = null
    resumedInterruptIds.value = []
    resumedLiveRunId.value = null
    runs.value = []
    runsHasMore.value = false
  }

  /** 同一 run 续写过（内容里留有请求批次）就说明当前 live 流只是续写段。 */
  function runHasResumeMarker(run: SessionRun | undefined): boolean {
    return Boolean(
      run?.content.some(item => item.type === 'approval_request' || item.type === 'call_request'),
    )
  }

  /** 这个中断批次已经提交成功了，卡片和输入框都不该再把它算作未决。 */
  function isInterruptResumed(interruptId: string): boolean {
    return resumedInterruptIds.value.includes(interruptId)
  }

  function resetCurrent(): void {
    const sessionId = currentSessionId.value
    clearTurnState()
    panels.closeTabs(sessionId)
    currentSessionId.value = null
    currentSession.value = null
    loadingSession.value = false
    sessionError.value = null
  }

  function abortActiveStream(): void {
    streamGeneration += 1
    streamAbort.value?.abort()
    streamAbort.value = null
    liveRun.value = null
    activeRunId.value = null
    cancelling.value = false
  }

  async function bootstrap(): Promise<void> {
    if (bootstrapping.value) return
    bootstrapping.value = true
    bootstrapError.value = null
    try {
      const [modelList, active, archived, groupList, caps] = await Promise.all([
        modelsApi.list(),
        sessionsApi.list({ status: 'active', limit: SESSION_PAGE_SIZE }),
        sessionsApi.list({ status: 'archived', limit: SESSION_PAGE_SIZE }),
        groupsApi.list(),
        capabilitiesApi.get().catch(error => {
          // 能力接口挂了不挡登录：后面的开关按"不可用"处理，但要留痕
          console.warn('读取平台能力失败，联网/出图开关按不可用', error)
          return null
        }),
      ])
      models.value = modelList.items
      modelsLoaded.value = true
      sessions.value = active.items
      archivedSessions.value = archived.items
      sessionsHasMore.value = active.items.length < active.total
      archivedHasMore.value = archived.items.length < archived.total
      groups.value = groupList
      capabilities.value = caps
      if (!caps?.web_search) webSearchEnabled.value = false
      if (!caps?.image_generation) imageGenerationEnabled.value = false
      sessionsLoaded.value = true
    } catch (error) {
      bootstrapError.value = errorMessage(error)
      throw error
    } finally {
      bootstrapping.value = false
    }
  }

  async function refreshModels(): Promise<void> {
    const list = await modelsApi.list()
    models.value = list.items
    modelsLoaded.value = true
  }

  function mergeSessionHead(head: ChatSession[], current: ChatSession[]): ChatSession[] {
    const headIds = new Set(head.map(item => item.id))
    return [...head, ...current.filter(item => !headIds.has(item.id))]
  }

  async function refreshSessions(): Promise<void> {
    const [active, archived] = await Promise.all([
      sessionsApi.list({ status: 'active', limit: SESSION_PAGE_SIZE }),
      sessionsApi.list({ status: 'archived', limit: SESSION_PAGE_SIZE }),
    ])
    const mergedActive = mergeSessionHead(active.items, sessions.value).slice(0, active.total)
    const mergedArchived = mergeSessionHead(archived.items, archivedSessions.value).slice(
      0,
      archived.total,
    )
    sessions.value = mergedActive
    archivedSessions.value = mergedArchived
    sessionsHasMore.value = mergedActive.length < active.total
    archivedHasMore.value = mergedArchived.length < archived.total
    sessionsLoaded.value = true
    if (currentSessionId.value) {
      const found = [...active.items, ...archived.items].find(
        item => item.id === currentSessionId.value,
      )
      if (found) currentSession.value = found
    }
  }

  async function loadMoreSessions(): Promise<void> {
    if (!sessionsHasMore.value || loadingMoreSessions.value) return
    loadingMoreSessions.value = true
    try {
      const page = await sessionsApi.list({
        status: 'active',
        limit: SESSION_PAGE_SIZE,
        offset: sessions.value.length,
      })
      const known = new Set(sessions.value.map(item => item.id))
      sessions.value = [...sessions.value, ...page.items.filter(item => !known.has(item.id))]
      sessionsHasMore.value = sessions.value.length < page.total
    } finally {
      loadingMoreSessions.value = false
    }
  }

  async function loadMoreArchivedSessions(): Promise<void> {
    if (!archivedHasMore.value || loadingMoreArchived.value) return
    loadingMoreArchived.value = true
    try {
      const page = await sessionsApi.list({
        status: 'archived',
        limit: SESSION_PAGE_SIZE,
        offset: archivedSessions.value.length,
      })
      const known = new Set(archivedSessions.value.map(item => item.id))
      archivedSessions.value = [
        ...archivedSessions.value,
        ...page.items.filter(item => !known.has(item.id)),
      ]
      archivedHasMore.value = archivedSessions.value.length < page.total
    } finally {
      loadingMoreArchived.value = false
    }
  }

  async function searchSessions(query: string): Promise<void> {
    const keyword = query.trim()
    const generation = ++searchGeneration
    searchQuery.value = keyword
    if (!keyword) {
      searchResults.value = []
      searching.value = false
      return
    }
    searching.value = true
    try {
      const page = await sessionsApi.list({
        q: keyword,
        limit: SEARCH_PAGE_SIZE,
      })
      if (generation !== searchGeneration) return
      searchResults.value = page.items
    } finally {
      if (generation === searchGeneration) searching.value = false
    }
  }

  async function openSession(id: UUID): Promise<void> {
    if (currentSessionId.value === id && currentSession.value) return
    clearTurnState()
    // 各会话的面板标签留在原处：切回来还能接着看
    currentSessionId.value = id
    currentSession.value = null
    loadingSession.value = true
    sessionError.value = null

    try {
      const [session, list] = await Promise.all([
        sessionsApi.get(id),
        runsApi.list(id, { limit: runsPageSize(RUNS_PAGE_SIZE, RUNS_PAGE_SIZE_COMPACT) }),
      ])
      if (currentSessionId.value !== id) return
      currentSession.value = session
      updateSessionInLists(session)
      pendingModelId.value = session.model_id
      pendingThinkingLevel.value = session.thinking_level
      runs.value = list.items
      runsHasMore.value = Boolean(list.has_more)
      loadingSession.value = false
      requestScroll()
      if (session.has_unread) void markSessionRead(id)

      if (session.active_run_id) {
        const activeRun = list.items.find(item => item.id === session.active_run_id)
        resumedLiveRunId.value = runHasResumeMarker(activeRun) ? session.active_run_id : null
        void attachStream(id, session.active_run_id, 0)
      } else {
        resumedLiveRunId.value = null
      }
    } catch (error) {
      if (currentSessionId.value !== id) return
      loadingSession.value = false
      sessionError.value = errorMessage(error)
      throw error
    }
  }

  async function loadEarlierRuns(): Promise<void> {
    if (!currentSessionId.value || !runs.value.length || loadingEarlier.value) return
    const first = runs.value[0]
    if (!first) return
    loadingEarlier.value = true
    try {
      const list = await runsApi.list(currentSessionId.value, {
        before_run_id: first.id,
        limit: runsPageSize(RUNS_PAGE_SIZE, RUNS_PAGE_SIZE_COMPACT),
      })
      runs.value = [...list.items, ...runs.value]
      runsHasMore.value = Boolean(list.has_more)
    } finally {
      loadingEarlier.value = false
    }
  }

  async function createSession(
    payload: {
      title?: string | null
      modelId?: number | null
      groupId?: number | null
    } = {},
  ): Promise<ChatSession> {
    if (!modelsLoaded.value && !models.value.length) {
      await refreshModels()
    }
    const session = await sessionsApi.create({
      title: payload.title ?? null,
      model_id: payload.modelId ?? currentModelId.value ?? defaultModel.value?.id ?? null,
      group_id: payload.groupId ?? null,
      thinking_level: currentThinkingLevel.value,
    })
    sessions.value = [session, ...sessions.value]
    currentSessionId.value = session.id
    currentSession.value = session
    runs.value = []
    runsHasMore.value = false
    requestScroll()
    return session
  }

  /** 开轮前的门禁：上一轮没跑完、或有卡片待确认，都不能再发。 */
  function assertCanStartRun(): void {
    if (busy.value) throw new Error('当前回复尚未结束')
    if (hasPendingInterrupts.value) throw new Error('请先处理上方的确认卡片')
  }

  /** 开关状态原样下发：后端默认值各不相同，省略字段可能把用户关掉的开关又打开。 */
  function runFlags(): Pick<
    RunCreatePayload,
    'enable_web_search' | 'enable_image_generation' | 'image_model_id'
  > {
    return {
      enable_web_search: effectiveWebSearch.value,
      enable_image_generation: effectiveImageGeneration.value,
      image_model_id: effectiveImageGeneration.value ? currentImageModel.value?.id : null,
    }
  }

  function buildRunPayload(input: SendMessageInput): RunCreatePayload {
    const flags = runFlags()
    if (input.retryRunId) {
      return {
        retry_run_id: input.retryRunId,
        model_id: currentModelId.value ?? undefined,
        tools: FRONTEND_TOOLS,
        ...flags,
      }
    }

    const attachments = (input.attachments ?? [])
      .filter(
        item =>
          item.status === 'ready' &&
          item.record &&
          (item.kind === 'image' || item.kind === 'video'),
      )
      .slice(0, maxImageAttachments.value)
      .map(item => ({
        kind: item.kind as 'image' | 'video',
        name: item.record?.name ?? item.file.name,
        media_type: item.record?.content_type || item.file.type || 'application/octet-stream',
        file_id: item.record!.id,
      }))

    const resources = (input.attachments ?? [])
      .filter(item => item.status === 'ready' && item.record && item.kind === 'resource')
      .slice(0, maxResourceFiles.value)
      .map(item => ({
        file_id: item.record!.id,
        name: item.record?.name ?? item.file.name,
      }))

    const payload: RunCreatePayload = {
      model_id: currentModelId.value ?? undefined,
      attachments,
      resources,
      tools: FRONTEND_TOOLS,
      ...flags,
    }
    if (input.text.trim()) payload.input = input.text.trim()
    if (input.parentRunId !== undefined) payload.parent_run_id = input.parentRunId
    return payload
  }

  async function refreshRunsAfterStart(sessionId: UUID): Promise<void> {
    try {
      const list = await runsApi.list(sessionId, {
        limit: runsPageSize(RUNS_REFRESH_PAGE_SIZE, RUNS_REFRESH_PAGE_SIZE_COMPACT),
      })
      if (currentSessionId.value !== sessionId) return
      runs.value = list.items
      runsHasMore.value = Boolean(list.has_more)
    } catch (error) {
      // 失败不阻塞开轮：事件流结束时还会再对齐一次，但要留痕
      console.warn('开轮后刷新 run 列表失败', error)
    }
  }

  /**
   * 409 说明该会话有正在跑的回复（多半在另一个标签页）。
   * 取到它的 run_id 就接入流观看，输入框文本由调用方保留；
   * run 恰好已结束时返回 null，调用方直接重试。
   */
  async function activeRunIdFromConflict(error: unknown, sessionId: UUID): Promise<string | null> {
    const api = toApiError(error)
    if (api.status !== 409) return null
    const payload = api.payload as { active_run_id?: unknown } | undefined
    if (typeof payload?.active_run_id === 'string' && payload.active_run_id) {
      return payload.active_run_id
    }
    try {
      const session = await sessionsApi.get(sessionId)
      return session.active_run_id
    } catch (error) {
      console.warn('409 后取活动 run 失败，按已结束处理', error)
      return null
    }
  }

  async function sendMessage(input: SendMessageInput): Promise<SendMessageOutcome> {
    assertCanStartRun()
    const text = input.text.trim()
    const attachments = input.attachments ?? []
    if (!text && attachments.filter(item => item.status === 'ready').length === 0) {
      throw new Error('请输入消息或添加附件')
    }

    let session = currentSession.value
    if (!session) {
      const fallbackName = attachments.find(item => item.status === 'ready')?.file.name
      const title = fileTitleFromContent(text || fallbackName || '', '新对话')
      session = await createSession({ title, groupId: input.groupId })
      if (currentSessionId.value !== session.id)
        return { sessionId: session.id, joinedActiveRun: false }
    }

    const payload = buildRunPayload({ ...input, text })
    let runId: string
    try {
      runId = await runsApi.create(session.id, payload)
    } catch (error) {
      if (currentSessionId.value !== session.id) throw error
      const existingRunId = await activeRunIdFromConflict(error, session.id)
      if (existingRunId === null) throw error
      // 别的标签页正在生成：接入它的流，消息文本留在输入框里
      activeRunId.value = existingRunId
      cancelling.value = false
      resumedLiveRunId.value = runHasResumeMarker(
        runs.value.find(item => item.id === existingRunId),
      ) ? existingRunId : null
      void attachStream(session.id, existingRunId, 0)
      requestScroll(true)
      return { sessionId: session.id, joinedActiveRun: true }
    }
    activeRunId.value = runId
    cancelling.value = false
    resumedLiveRunId.value = null
    await refreshRunsAfterStart(session.id)
    if (currentSessionId.value !== session.id) {
      return { sessionId: session.id, joinedActiveRun: false }
    }
    requestScroll(true)
    void attachStream(session.id, runId, 0)
    return { sessionId: session.id, joinedActiveRun: false }
  }

  async function regenerate(run: SessionRun): Promise<void> {
    assertCanStartRun()
    const sessionId = currentSessionId.value
    if (!sessionId) throw new Error('当前没有会话')
    const runId = await runsApi.create(sessionId, {
      retry_run_id: run.id,
      model_id: currentModelId.value ?? undefined,
      tools: FRONTEND_TOOLS,
      ...runFlags(),
    })
    if (currentSessionId.value !== sessionId) return
    activeRunId.value = runId
    resumedLiveRunId.value = null
    await refreshRunsAfterStart(sessionId)
    if (currentSessionId.value !== sessionId) return
    requestScroll(true)
    void attachStream(sessionId, runId, 0)
  }

  async function editMessage(run: SessionRun, text: string): Promise<void> {
    assertCanStartRun()
    const sessionId = currentSessionId.value
    if (!sessionId) throw new Error('当前没有会话')
    const attachments = run.content.flatMap(item => {
      if (
        (item.type === 'image' || item.type === 'video') &&
        item.role === 'user' &&
        item.file_id
      ) {
        return [
          {
            kind: item.type,
            name: item.name || item.alt || '附件',
            media_type: item.media_type || 'application/octet-stream',
            file_id: item.file_id,
          },
        ]
      }
      return []
    })
    const resources = run.content.flatMap(item => {
      if (item.type === 'resource' && item.role === 'user') {
        return [{ file_id: item.file_id, name: item.name }]
      }
      return []
    })
    const runId = await runsApi.create(sessionId, {
      input: text.trim(),
      parent_run_id: run.parent_run_id,
      model_id: currentModelId.value ?? undefined,
      attachments,
      resources,
      tools: FRONTEND_TOOLS,
      ...runFlags(),
    })
    if (currentSessionId.value !== sessionId) return
    editingRun.value = null
    editingText.value = ''
    activeRunId.value = runId
    resumedLiveRunId.value = null
    await refreshRunsAfterStart(sessionId)
    if (currentSessionId.value !== sessionId) return
    requestScroll(true)
    void attachStream(sessionId, runId, 0)
  }

  async function cancelRun(): Promise<void> {
    if (!activeRunId.value || !currentSessionId.value) return
    cancelling.value = true
    try {
      await runsApi.cancel(currentSessionId.value, activeRunId.value)
    } catch (error) {
      cancelling.value = false
      throw error
    }
  }

  async function switchBranch(run: SessionRun, index: number): Promise<void> {
    if (busy.value || !currentSessionId.value || !run.branch) return
    const leaf = run.branch.leaves[index]
    if (!leaf) return
    const sessionId = currentSessionId.value
    const session = await sessionsApi.switchLeaf(sessionId, leaf)
    if (currentSessionId.value !== sessionId) return
    currentSession.value = session
    updateSessionInLists(session)
    const list = await runsApi.list(sessionId, {
      limit: runsPageSize(RUNS_PAGE_SIZE, RUNS_PAGE_SIZE_COMPACT),
    })
    if (currentSessionId.value !== sessionId) return
    runs.value = list.items
    runsHasMore.value = Boolean(list.has_more)
    requestScroll()
  }

  function applyEvent(event: AgUiEvent): void {
    const live = liveRun.value
    if (live) applyAgUiEvent(live, event)
  }

  async function settleRun(sessionId: UUID, runId: string, generation: number): Promise<void> {
    const deadline = Date.now() + SETTLE_TIMEOUT_MS
    let attempt = 0
    while (true) {
      // 首轮 180ms 快查一次，之后 2s → 4s → 8s → 15s 封顶，别把轮询打满
      await sleep(
        attempt === 0
          ? SETTLE_FIRST_DELAY_MS
          : Math.min(2_000 * 2 ** (attempt - 1), SETTLE_MAX_DELAY_MS),
      )
      attempt += 1
      if (generation !== streamGeneration || currentSessionId.value !== sessionId) return
      try {
        const session = await sessionsApi.get(sessionId)
        if (generation !== streamGeneration || currentSessionId.value !== sessionId) return
        if (session.active_run_id === runId) {
          // 事件流先断了但后端还在跑：保留 live 视图和停止按钮，别把半截 run 固化成已结束。
          if (Date.now() >= deadline) {
            console.warn(`等待 run ${runId} 结束超时：后端仍显示它在运行`)
            return
          }
          continue
        }
        const list = await runsApi.list(sessionId, {
          limit: runsPageSize(RUNS_SETTLE_PAGE_SIZE, RUNS_SETTLE_PAGE_SIZE_COMPACT),
        })
        if (generation !== streamGeneration || currentSessionId.value !== sessionId) return
        const run = list.items.find(item => item.id === runId)
        if (run?.status === 'running') {
          if (Date.now() >= deadline) {
            console.warn(`等待 run ${runId} 结束超时：run 状态仍是 running`)
            return
          }
          continue
        }
        currentSession.value = session
        updateSessionInLists(session)
        runs.value = list.items
        runsHasMore.value = Boolean(list.has_more)
        if (activeRunId.value === runId) {
          activeRunId.value = null
          liveRun.value = null
        }
        cancelling.value = false
        resumingInterruptId.value = null
        if (run && session.has_unread) {
          await markSessionRead(sessionId)
        }
        void refreshSessions().catch(() => undefined)
        return
      } catch {
        if (Date.now() >= deadline) return
      }
    }
  }

  async function attachStream(sessionId: UUID, runId: string, after = 0): Promise<void> {
    // 兜底：调用方在 await 之间切走了会话，这条流不该再挂到当前视图上
    if (currentSessionId.value !== sessionId) return
    streamGeneration += 1
    const generation = streamGeneration
    streamAbort.value?.abort()
    streamAbort.value = null
    activeRunId.value = runId
    cancelling.value = false
    liveRun.value = {
      runId,
      sessionId,
      blocks: [],
      usage: null,
      compaction: null,
      error: null,
      errorCode: null,
      connected: false,
      finished: false,
    }

    let sequence = after
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (generation !== streamGeneration) return
      const controller = new AbortController()
      streamAbort.value = controller
      try {
        await streamRun({
          url: runsApi.eventsUrl(sessionId, runId, sequence),
          signal: controller.signal,
          onSequence: value => {
            sequence = value
          },
          onOpen: () => {
            if (generation === streamGeneration && liveRun.value) liveRun.value.connected = true
          },
          onEvent: event => {
            if (generation === streamGeneration) applyEvent(event)
          },
        })
        break
      } catch (error) {
        if (isAbort(controller.signal.reason as Error) || controller.signal.aborted) return
        if (error instanceof StreamGoneError) break
        if (generation !== streamGeneration) return
        if (attempt >= 2) {
          if (liveRun.value) liveRun.value.error = errorMessage(error)
          break
        }
        await sleep(650)
      }
    }

    if (generation !== streamGeneration) return
    if (liveRun.value) liveRun.value.finished = true
    await settleRun(sessionId, runId, generation)
  }

  async function resumePendingBatch(payload: {
    interruptId: string
    approvals: Record<string, boolean>
    calls: Record<string, unknown>
  }): Promise<void> {
    if (!currentSessionId.value) throw new Error('当前没有会话')
    if (busy.value) throw new Error('正在生成中，请稍后再试')
    if (resumingInterruptId.value === payload.interruptId) return
    const sessionId = currentSessionId.value
    resumingInterruptId.value = payload.interruptId
    try {
      const runId = await runsApi.resume(sessionId, {
        interrupt_id: payload.interruptId,
        approvals: payload.approvals,
        calls: payload.calls,
        tools: FRONTEND_TOOLS,
        ...runFlags(),
        model_id: currentModelId.value ?? undefined,
      })
      // 后端已经收下答案：卡片和输入框都不该再等工具结果回到快照里才算未决
      resumedInterruptIds.value = [...resumedInterruptIds.value, payload.interruptId]
      if (currentSessionId.value !== sessionId) return
      activeRunId.value = runId
      resumedLiveRunId.value = runId
      await refreshRunsAfterStart(sessionId)
      if (currentSessionId.value !== sessionId) return
      requestScroll(true)
      void attachStream(sessionId, runId, 0)
    } finally {
      // 只在 catch 里释放会留下永久锁：成功后重试会被开头那句同 id 判断静默吞掉
      resumingInterruptId.value = null
    }
  }

  function beginEditing(run: SessionRun): void {
    if (busy.value || hasPendingInterrupts.value) return
    const text = run.content
      .flatMap(item => {
        if (item.type === 'text' && item.role === 'user') return [item.text]
        return []
      })
      .join('\n\n')
    editingRun.value = run
    editingText.value = text
  }

  function cancelEditing(): void {
    editingRun.value = null
    editingText.value = ''
  }

  function setWebSearchEnabled(value: boolean): void {
    webSearchEnabled.value = value
  }

  function setImageModel(id: number | null): void {
    if (id === null) {
      imageGenerationEnabled.value = false
      return
    }
    if (!imageModels.value.some(model => model.id === id)) return
    imageModelId.value = id
    imageGenerationEnabled.value = true
  }

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
    models,
    modelsLoaded,
    groups,
    sessions,
    archivedSessions,
    sessionsHasMore,
    archivedHasMore,
    loadingMoreSessions,
    loadingMoreArchived,
    searchQuery,
    searchResults,
    searching,
    sessionsLoaded,
    bootstrapping,
    bootstrapError,
    currentSessionId,
    currentSession,
    runs,
    runsHasMore,
    loadingSession,
    loadingEarlier,
    sessionError,
    activeRunId,
    liveRun,
    cancelling,
    pendingModelId,
    pendingThinkingLevel,
    activeModels,
    defaultModel,
    currentModelId,
    currentModel,
    thinkingLevels,
    currentThinkingLevel,
    busy,
    isStreaming,
    hasMessages,
    capabilities,
    webSearchAvailable,
    webSearchEnabled,
    effectiveWebSearch,
    imageGenerationAvailable,
    imageGenerationEnabled,
    effectiveImageGeneration,
    imageModels,
    imageModelId,
    currentImageModel,
    setImageModel,
    maxUploadBytes,
    maxImageAttachments,
    maxResourceFiles,
    toolResultsByCallId,
    resumedLiveRunId,
    hasPendingInterrupts,
    resumingInterruptId,
    isInterruptResumed,
    editingRun,
    editingText,
    bootstrap,
    refreshModels,
    refreshSessions,
    loadMoreSessions,
    loadMoreArchivedSessions,
    searchSessions,
    openSession,
    loadEarlierRuns,
    createSession,
    sendMessage,
    regenerate,
    editMessage,
    cancelRun,
    switchBranch,
    renameSession,
    resumePendingBatch,
    beginEditing,
    cancelEditing,
    setWebSearchEnabled,
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
    resetCurrent,
  }
})
