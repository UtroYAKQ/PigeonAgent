import { computed, onUnmounted, ref, type Ref } from "vue";

import {
  cancelRun,
  getSession,
  listRuns,
  resumeRun,
  runFrames,
  startRun,
  switchLeaf,
  updateSession,
} from "../lib/api";
import { ApiError, RunGoneError } from "../lib/errors";
import { newLiveBlock, reduceLive } from "../lib/live";
import { deriveThread, projectUserBlock } from "../lib/projector";
import { declaredTools } from "../tools";
import type {
  DisplayBlock,
  InterruptView,
  Item,
  OutgoingAttachment,
  OutgoingResource,
  Session,
  SessionRun,
} from "../types";

const TERMINAL = new Set(["RUN_FINISHED", "RUN_ERROR"]);
/** 首屏 / 每页的 run 数。 */
const PAGE_SIZE = 80;

export function useThread(sessionId: string, modelId: Ref<number | null>) {
  const session = ref<Session | null>(null);
  const runs = ref<SessionRun[]>([]);
  const optimisticUser = ref<DisplayBlock | null>(null);
  const live = ref<DisplayBlock | null>(null);
  /** 正在跟随的 run：从历史投影里排除，避免和 SSE 重放出来的半截内容重复。 */
  const liveRunId = ref<string | null>(null);
  const running = ref(false);
  const loading = ref(true);
  const loadingOlder = ref(false);
  const hasMore = ref(false);
  const error = ref<string | null>(null);
  /** 会话已经被删掉了（别处删的或后端清库）：留在原地只会显示一堆「not found」，得退出去。 */
  const missing = ref(false);

  function noteFailure(cause: unknown): void {
    error.value = cause instanceof Error ? cause.message : String(cause);
    missing.value = cause instanceof ApiError && cause.status === 404;
  }

  /** 一次扫描同时给出消息块和未决批次；活动 run 交给 SSE 渲染，不进历史投影。 */
  const derived = computed(() =>
    deriveThread(runs.value, { excludeRunId: liveRunId.value }),
  );
  const interrupts = computed<InterruptView[]>(() => derived.value.pending);
  /** 后端权威的未决批次数：可能包含早于当前分页、前端看不见的卡片。 */
  const pendingCount = computed(() => session.value?.pending_batches ?? 0);
  const history = computed(() => derived.value.blocks);
  const blocks = computed<DisplayBlock[]>(() => {
    const list = [...history.value];
    let derivedUser = false;
    if (liveRunId.value) {
      const active = runs.value.find((run) => run.id === liveRunId.value);
      const userBlock = active ? projectUserBlock(active) : null;
      if (userBlock) {
        list.push(userBlock);
        derivedUser = true;
      }
    }
    if (optimisticUser.value && !derivedUser) list.push(optimisticUser.value);
    if (live.value) list.push(live.value);
    return list;
  });

  let controller: AbortController | null = null;
  let generation = 0;

  /** 临时渲染态（活动块 / 跟随的 run / 乐观气泡）只有这一处清：散着清最容易漏。 */
  function clearLive(): void {
    live.value = null;
    liveRunId.value = null;
    optimisticUser.value = null;
  }

  function userBlock(
    prompt: string,
    attachments: OutgoingAttachment[] = [],
    resources: OutgoingResource[] = [],
  ): DisplayBlock {
    const items: Item[] = [];
    if (prompt.trim()) {
      items.push({
        type: "text",
        id: "optimistic-text",
        text: prompt,
        role: "user",
        status: "done",
      });
    }
    resources.forEach((resource) => {
      items.push({
        type: "resource",
        id: `optimistic-resource-${resource.storage_key}`,
        storageKey: resource.storage_key,
        name: resource.name,
        mediaType: resource.media_type,
        size: resource.size,
      });
    });
    attachments.forEach((attachment, index) => {
      items.push({
        type: attachment.kind,
        id: `optimistic-${attachment.kind}-${index}`,
        url: attachment.preview ?? "",
        fileId: attachment.file_id,
        mediaType: attachment.media_type,
        alt: attachment.name,
      });
    });
    return {
      id: `optimistic:${Date.now()}`,
      role: "user",
      items,
      status: "done",
      runIds: [],
    };
  }

  async function loadPage(beforeRunId?: string) {
    return listRuns(sessionId, {
      limit: PAGE_SIZE,
      ...(beforeRunId == null ? {} : { beforeRunId }),
    });
  }

  async function load(followActive = true): Promise<void> {
    try {
      const nextSession = await getSession(sessionId);
      session.value = nextSession;
      // 首屏只取靠近叶子的最后一页，更早的靠「加载更早」沿分支向前翻
      const page = await loadPage();
      runs.value = page.items;
      hasMore.value = page.has_more ?? false;
      if (nextSession.model_id != null) modelId.value = nextSession.model_id;
      error.value = null;
    } catch (cause) {
      noteFailure(cause);
    } finally {
      loading.value = false;
    }
    const active = session.value?.active_run_id;
    if (followActive && active && !running.value) {
      void follow(active);
    }
  }

  /** 沿当前分支向前翻一页，返回新增条数供调用方补偿滚动位置。 */
  async function loadOlder(): Promise<number> {
    const oldest = runs.value[0];
    if (!oldest || loadingOlder.value) return 0;
    loadingOlder.value = true;
    try {
      const page = await loadPage(oldest.id);
      runs.value = [...page.items, ...runs.value];
      hasMore.value = page.has_more ?? false;
      return page.items.length;
    } catch (cause) {
      noteFailure(cause);
      return 0;
    } finally {
      loadingOlder.value = false;
    }
  }

  /** run 结束后刷新：保留仍在当前分支上的旧页，换掉从叶子开始的最新页。 */
  async function refresh(): Promise<void> {
    try {
      const nextSession = await getSession(sessionId);
      session.value = nextSession;
      const page = await loadPage();
      const tail = new Set(page.items.map((run) => run.id));
      const parentOf = new Map(runs.value.map((run) => [run.id, run.parent_run_id]));
      const above = new Set<string>();
      let current = page.items[0]?.parent_run_id ?? null;
      while (current && parentOf.has(current) && !above.has(current)) {
        above.add(current);
        current = parentOf.get(current) ?? null;
      }
      const older = runs.value.filter((run) => !tail.has(run.id) && above.has(run.id));
      runs.value = [...older, ...page.items];
      hasMore.value = page.has_more ?? false;
    } catch (cause) {
      noteFailure(cause);
      await load(false);
    }
  }

  async function consume(runId: string, after = 0): Promise<void> {
    const mine = ++generation;
    controller?.abort();
    controller = new AbortController();
    // 帧合并：SSE 增量先折进局部变量，每帧最多往响应式状态写一次。
    // 刷新后是从 0 重放整段事件，不合并的话几百次全量 markdown 重解析会挤在同一秒里。
    let folded = live.value;
    let raf = 0;
    const publish = (): void => {
      raf = 0;
      if (folded) live.value = folded;
    };
    const stop = (): void => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };
    try {
      for await (const frame of runFrames(sessionId, runId, controller.signal, after)) {
        if (mine !== generation) return;
        folded = reduceLive(folded ?? newLiveBlock(`live:${runId}`), frame.event);
        if (TERMINAL.has(frame.event.type)) {
          stop();
          publish();
          break;
        }
        if (!raf) raf = requestAnimationFrame(publish);
      }
    } catch (cause) {
      if (mine !== generation) return;
      if (cause instanceof RunGoneError) {
        // run 结束得比订阅快：队列已摘除，直接读落库结果
      } else if (cause instanceof DOMException && cause.name === "AbortError") {
        // 用户停止或切换会话
      } else {
        noteFailure(cause);
      }
    } finally {
      stop();
      if (mine === generation) {
        running.value = false;
        await refresh();
        clearLive();
      }
      if (controller && mine === generation) controller = null;
    }
  }

  async function follow(runId: string): Promise<void> {
    running.value = true;
    liveRunId.value = runId;
    optimisticUser.value = null;
    live.value = newLiveBlock(`live:${runId}`);
    await consume(runId, 0);
  }

  /** 跑一轮：input 是新提问，parentRunId 指定从哪一处开分支，retryRunId 复制旧提问。 */
  async function beginRun(start: {
    input?: string;
    attachments?: OutgoingAttachment[];
    resources?: OutgoingResource[];
    parentRunId?: string | null;
    retryRunId?: string | null;
  }): Promise<void> {
    error.value = null;
    running.value = true;
    const attachments = start.attachments ?? [];
    const resources = start.resources ?? [];
    optimisticUser.value =
      start.input?.trim() || attachments.length > 0 || resources.length > 0
        ? userBlock(start.input ?? "", attachments, resources)
        : null;
    live.value = newLiveBlock();
    try {
      const run = await startRun(sessionId, {
        ...(start.input == null ? {} : { input: start.input }),
        ...(attachments.length > 0 ? { attachments } : {}),
        ...(resources.length > 0 ? { resources } : {}),
        ...(start.parentRunId === undefined ? {} : { parentRunId: start.parentRunId }),
        ...(start.retryRunId == null ? {} : { retryRunId: start.retryRunId }),
        tools: declaredTools(),
        modelId: modelId.value,
      });
      liveRunId.value = run.run_id;
      // 分支导航由后端算（run.branch）：不先刷一次，同一提问的 1/2 要等这轮跑完才出现。
      await refresh().catch(() => {});
      if (!session.value?.title && start.input) {
        void updateSession(sessionId, { title: start.input.slice(0, 36) })
          .then((updated) => {
            session.value = updated;
          })
          .catch(() => {});
      }
      await consume(run.run_id);
    } catch (cause) {
      noteFailure(cause);
      running.value = false;
      clearLive();
      await load(false);
    }
  }

  async function send(
    prompt: string,
    attachments: OutgoingAttachment[] = [],
    resources: OutgoingResource[] = [],
  ): Promise<void> {
    if (
      (!prompt.trim() && attachments.length === 0 && resources.length === 0) ||
      running.value ||
      interrupts.value.length > 0 ||
      pendingCount.value > 0
    ) {
      return;
    }
    await beginRun({
      input: prompt.trim() || undefined,
      attachments,
      resources,
    });
  }

  /** 重新生成：复制这条 turn 的用户输入，从它的父节点另起一条回答。 */
  async function regenerate(block: DisplayBlock): Promise<void> {
    if (
      running.value ||
      interrupts.value.length > 0 ||
      pendingCount.value > 0 ||
      !block.answerTo
    ) {
      return;
    }
    await beginRun({ retryRunId: block.answerTo });
  }

  /** 改提问重发：在原 turn 的父节点下挂一个新 turn。 */
  async function editResend(block: DisplayBlock, text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || running.value || !block.runId) return;
    const parentId = block.parentRunId ?? null;
    // 先把视图收窄到父节点：否则编辑后的新消息会先追加在旧分支末尾，看起来像续聊
    if (parentId === null) {
      runs.value = [];
    } else {
      const parentIndex = runs.value.findIndex((run) => run.id === parentId);
      if (parentIndex >= 0) {
        runs.value = runs.value.slice(0, parentIndex + 1);
      } else {
        const editedIndex = runs.value.findIndex((run) => run.id === block.runId);
        if (editedIndex >= 0) runs.value = runs.value.slice(0, editedIndex);
      }
    }
    await beginRun({ input: trimmed, parentRunId: parentId });
  }

  /** 切到某个分支：叶子挪到那条分支的末端，再按新分支重读。 */
  async function goBranch(leafRunId: string): Promise<void> {
    if (running.value) return;
    try {
      session.value = await switchLeaf(sessionId, leafRunId);
      await load(false);
    } catch (cause) {
      noteFailure(cause);
      await load(false);
    }
  }

  async function answer(
    interruptId: string,
    payload: { approvals?: Record<string, boolean>; calls?: Record<string, unknown> },
  ): Promise<boolean> {
    if (running.value) return false;
    error.value = null;
    running.value = true;
    optimisticUser.value = null;
    live.value = newLiveBlock();
    try {
      const run = await resumeRun(sessionId, {
        interruptId,
        approvals: payload.approvals,
        calls: payload.calls,
        tools: declaredTools(),
        ...(modelId.value == null ? {} : { model_id: modelId.value }),
      });
      liveRunId.value = run.run_id;
      await consume(run.run_id);
      return true;
    } catch (cause) {
      noteFailure(cause);
      running.value = false;
      clearLive();
      await load(false);
      return false;
    }
  }

  let stopping = false;

  async function stop(): Promise<void> {
    if (stopping) return;
    stopping = true;
    // session.active_run_id 要等 run 收尾刷新才准，正在跟的这个 id 才是当前 run
    const runId = liveRunId.value ?? session.value?.active_run_id;
    controller?.abort();
    controller = null;
    generation += 1;
    // 乐观气泡和活动块先摘掉，重读后以落库结果为准
    clearLive();
    try {
      if (runId) {
        try {
          await cancelRun(sessionId, runId);
        } catch {
          // run 已经结束也会走到这里，刷新即可
        }
      }
      // 后台任务和 SSE 是分离的，断流不算取消，无论如何都重读一次状态
      await load(false);
    } finally {
      // running 一直保持到取消 + 重读结束：提前放开会让用户秒发的新消息撞上还在收尾的 run
      stopping = false;
      running.value = false;
    }
  }

  async function setModel(id: number): Promise<void> {
    modelId.value = id;
    if (!session.value) return;
    try {
      session.value = await updateSession(sessionId, { model_id: id });
    } catch (cause) {
      noteFailure(cause);
    }
  }

  void load(true);
  onUnmounted(() => {
    generation += 1;
    controller?.abort();
  });

  return {
    session,
    blocks,
    running,
    loading,
    loadingOlder,
    hasMore,
    loadOlder,
    error,
    missing,
    interrupts,
    pendingCount,
    send,
    answer,
    regenerate,
    editResend,
    goBranch,
    stop,
    setModel,
  };
}
