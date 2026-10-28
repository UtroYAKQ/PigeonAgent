import type {
  AguiEvent,
  FileRead,
  FrontendToolDeclaration,
  LlmModel,
  LlmModelList,
  OutgoingAttachment,
  OutgoingResource,
  RunList,
  RunRead,
  Session,
  SessionGroup,
  SessionGroupList,
  SessionList,
} from "../types";
import { authedFetch, tryRefresh, loadAuth } from "./auth";
import { ApiError, RunGoneError, errorFromResponse } from "./errors";

const api = import.meta.env.VITE_API_PREFIX ?? "/api/v1";

export const API_PREFIX = api;

async function json<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) throw errorFromResponse(response, body);
  return body as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return json<T>(await authedFetch(path, init));
}

/** 204/空响应的写操作：只关心成功与否，错误体照样解析出 detail。 */
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await authedFetch(path, init);
  if (response.ok) return;
  throw errorFromResponse(response, await response.json().catch(() => null));
}

const jsonHeaders = { "content-type": "application/json" };

export const listSessions = (limit = 100): Promise<SessionList> =>
  request<SessionList>(`/sessions?limit=${limit}`);

export const getSession = (sessionId: string): Promise<Session> =>
  request<Session>(`/sessions/${sessionId}`);

export const createSession = (
  modelId: number | null = null,
  groupId: number | null = null,
): Promise<Session> =>
  request<Session>("/sessions", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      ...(modelId == null ? {} : { model_id: modelId }),
      ...(groupId == null ? {} : { group_id: groupId }),
    }),
  });

export const updateSession = (
  sessionId: string,
  patch: { title?: string; model_id?: number; status?: string; group_id?: number | null },
): Promise<Session> =>
  request<Session>(`/sessions/${sessionId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(patch),
  });

export const listGroups = (): Promise<SessionGroupList> => request<SessionGroupList>("/groups");

export const createGroup = (name: string): Promise<SessionGroup> =>
  request<SessionGroup>("/groups", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ name }),
  });

export const renameGroup = (groupId: number, name: string): Promise<SessionGroup> =>
  request<SessionGroup>(`/groups/${groupId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify({ name }),
  });

export const deleteGroup = (groupId: number): Promise<void> =>
  requestVoid(`/groups/${groupId}`, { method: "DELETE" });

export const deleteSession = (sessionId: string): Promise<void> =>
  requestVoid(`/sessions/${sessionId}`, { method: "DELETE" });

export interface RunPageParams {
  limit?: number;
  beforeRunId?: string;
}

/** 当前分支上的 run（根→叶）。 */
export const listRuns = (
  sessionId: string,
  params: RunPageParams = {},
): Promise<RunList> => {
  const query = new URLSearchParams();
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.beforeRunId != null) query.set("before_run_id", params.beforeRunId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<RunList>(`/sessions/${sessionId}/runs${suffix}`);
};

/** 切换当前分支；leafRunId 传 null 表示回到空会话。 */
export const switchLeaf = (sessionId: string, leafRunId: string | null): Promise<Session> =>
  request<Session>(`/sessions/${sessionId}/leaf`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ leaf_run_id: leafRunId }),
  });

export const listModels = (): Promise<LlmModelList> =>
  request<LlmModelList>("/models?limit=200");

export const createModel = (payload: Record<string, unknown>): Promise<LlmModel> =>
  request<LlmModel>("/models", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });

export const updateModel = (
  modelId: number,
  payload: Record<string, unknown>,
): Promise<LlmModel> =>
  request<LlmModel>(`/models/${modelId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });

export const deleteModel = (modelId: number): Promise<void> =>
  requestVoid(`/models/${modelId}`, { method: "DELETE" });

export interface RunStart {
  /** 新的用户消息；和 retryRunId 至少给一个。 */
  input?: string;
  /** 随消息上传的附件。 */
  attachments?: OutgoingAttachment[];
  /** 走 /files 登记过的文件引用；提示词里渲染成 <resource/> 标签。 */
  resources?: OutgoingResource[];
  /** 本轮可用的前端工具；每轮都带上，重新生成时模型才看得到同一批。 */
  tools?: FrontendToolDeclaration[];
  /** 从这条 run 的父节点开新分支；显式 null 表示在根处开分支。 */
  parentRunId?: string | null;
  /** 复制这条 turn 的用户输入，从它的父节点另起回答（重新生成）。 */
  retryRunId?: string | null;
  modelId?: number | null;
}

export const startRun = (sessionId: string, start: RunStart): Promise<RunRead> =>
  request<RunRead>(`/sessions/${sessionId}/runs`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      ...(start.input == null ? {} : { input: start.input }),
      ...(start.attachments?.length
        ? {
            attachments: start.attachments.map(({ kind, name, media_type, file_id }) => ({
              kind,
              name,
              media_type,
              file_id,
            })),
          }
        : {}),
      ...(start.resources?.length
        ? {
            resources: start.resources.map(({ storage_key, name }) => ({
              storage_key,
              name,
            })),
          }
        : {}),
      ...(start.tools?.length ? { tools: start.tools } : {}),
      ...(start.parentRunId === undefined ? {} : { parent_run_id: start.parentRunId }),
      ...(start.retryRunId == null ? {} : { retry_run_id: start.retryRunId }),
      ...(start.modelId == null ? {} : { model_id: start.modelId }),
    }),
  });

export const resumeRun = (
  sessionId: string,
  payload: {
    /** 要回应哪个中断批次。 */
    interruptId: string;
    approvals?: Record<string, boolean>;
    calls?: Record<string, unknown>;
    tools?: FrontendToolDeclaration[];
    model_id?: number;
  },
): Promise<RunRead> =>
  request<RunRead>(`/sessions/${sessionId}/runs/resume`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      interrupt_id: payload.interruptId,
      ...(payload.approvals ? { approvals: payload.approvals } : {}),
      ...(payload.calls ? { calls: payload.calls } : {}),
      ...(payload.tools?.length ? { tools: payload.tools } : {}),
      ...(payload.model_id == null ? {} : { model_id: payload.model_id }),
    }),
  });

export const cancelRun = (sessionId: string, runId: string): Promise<void> =>
  requestVoid(`/sessions/${sessionId}/runs/${runId}/cancel`, { method: "POST" });

/** 小文件直传；401 之类失败由调用方决定是否回退 base64 附件。 */
export const uploadFile = async (file: File): Promise<FileRead> => {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await authedFetch("/files", { method: "POST", body: form });
  if (!response.ok) {
    throw errorFromResponse(response, await response.json().catch(() => null));
  }
  return (await response.json()) as FileRead;
};

export interface RunFrame {
  id: number;
  event: AguiEvent;
}

/** 读 AG-UI SSE：兼容 `id:`、注释心跳和 CRLF，流结束/abort 时退出。 */
export async function* runFrames(
  sessionId: string,
  runId: string,
  signal: AbortSignal,
  after = 0,
): AsyncGenerator<RunFrame> {
  let response = await authedFetch(
    `/sessions/${sessionId}/runs/${runId}/events?after=${after}`,
    { headers: { accept: "text/event-stream" }, signal },
  );
  if (response.status === 401) {
    // SSE 属长连接：进流前先尽力刷新一次，失败如实抛给上层
    if (await tryRefresh(loadAuth() ?? { access: "", refresh: "", user: null })) {
      response = await authedFetch(
        `/sessions/${sessionId}/runs/${runId}/events?after=${after}`,
        { headers: { accept: "text/event-stream" }, signal },
        false,
      );
    }
  }
  if (response.status === 410) throw new RunGoneError();
  if (!response.ok) {
    throw new ApiError(response.status, await response.text().catch(() => response.statusText));
  }
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let nextId = after + 1;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let id = nextId;
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("id:")) {
            const parsed = Number.parseInt(line.slice(3).trim(), 10);
            if (Number.isFinite(parsed)) id = parsed;
          } else if (line.startsWith("data:")) {
            data.push(line.slice(5).replace(/^ /, ""));
          }
        }
        if (data.length > 0) {
          nextId = id + 1;
          yield { id, event: JSON.parse(data.join("\n")) as AguiEvent };
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
