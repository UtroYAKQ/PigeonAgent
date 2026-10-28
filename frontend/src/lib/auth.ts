import { ref } from "vue";

import { API_PREFIX as api } from "./api";
import { ApiError, errorFromResponse } from "./errors";
import type { OneTimeRegisterResult, TokenPair, UserRead } from "../types";

const STORAGE_KEY = "pigeon.auth";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
}

interface StoredAuth {
  access: string;
  refresh: string;
  user: UserRead | null;
}

/** 全局登录态；未登录时 App 渲染 AuthGate 而不是主界面。 */
export function loadAuth(): StoredAuth | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAuth;
    return typeof parsed.access === "string" && typeof parsed.refresh === "string"
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function store(auth: StoredAuth | null): void {
  if (auth) localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  else localStorage.removeItem(STORAGE_KEY);
  currentUser.value = auth?.user ?? null;
}

/** 启动时同步读一次：有登录态就先把身份设上，刷新时不会闪一下登录页。 */
const initial = loadAuth();
export const currentUser = ref<UserRead | null>(initial?.user ?? null);

/** 有 token 就算有会话（用户对象可能还没拉回来）。 */
export function hasSession(): boolean {
  const stored = loadAuth();
  return Boolean(stored?.access || stored?.refresh);
}

/** 调 /auth/me 顺带确认 token 没过期；失败换未登录状态。 */
export async function probeSession(): Promise<void> {
  if (!loadAuth()) return;
  try {
    await adoptIdentity();
  } catch {
    store(null);
  }
}

function tokensFromBody(body: { access_token?: string; refresh_token?: string }): void {
  const stored = loadAuth();
  store({
    access: body.access_token ?? "",
    refresh: body.refresh_token ?? stored?.refresh ?? "",
    user: stored?.user ?? null,
  });
}

/** 拉一次身份并把 token + user 一起落库；刷新页面后只认这份身份。 */
async function adoptIdentity(): Promise<UserRead> {
  const me = await requestJson<UserRead>("/auth/me");
  const stored = loadAuth();
  if (stored) store({ ...stored, user: me });
  return me;
}

export async function login(email: string, password: string): Promise<UserRead> {
  tokensFromBody(await postJson<TokenPair>("/auth/login", { email, password }));
  return adoptIdentity();
}

export async function register(
  email: string,
  password: string,
  displayName?: string,
): Promise<OneTimeRegisterResult> {
  const body = await postJson<{
    verification_required: boolean;
    tokens?: TokenPair | null;
  }>("/auth/register", {
    ...(displayName ? { display_name: displayName } : {}),
    email,
    password,
  });
  if (body.tokens) {
    // 没开邮箱验证时注册即登录；补一次 me 拉齐全局身份
    tokensFromBody(body.tokens);
    await adoptIdentity();
  }
  return { verifyRequired: body.verification_required || !body.tokens };
}

export async function verify(email: string, code: string): Promise<void> {
  tokensFromBody(await postJson<TokenPair>("/auth/verify", { email, code }));
  await adoptIdentity();
}

export async function resendCode(email: string): Promise<void> {
  await postJson("/auth/resend", { email });
}

export function logout(): void {
  store(null);
}

// ---------------------------------------------------------------- 内部工具

async function requestJson<T>(path: string, retries = 0): Promise<T> {
  const stored = loadAuth();
  const response = await fetch(`${api}${path}`, {
    headers: stored ? { authorization: `Bearer ${stored.access}` } : {},
  });
  if (response.status === 401 && retries < 1 && stored) {
    if (await tryRefresh(stored)) return requestJson<T>(path, retries + 1);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw errorFromResponse(response, body);
  return body as T;
}

async function postJson<T = unknown>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${api}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => null)) as T | null;
  if (!response.ok) throw errorFromResponse(response, body);
  return body as T;
}

let refreshInFlight: Promise<boolean> | null = null;

/** 用 refresh token 换一对新的；并发 401 时只发一次请求，单 例复用。 */
export async function tryRefresh(
  stored: StoredAuth = loadAuth() ?? { access: "", refresh: "", user: null },
): Promise<boolean> {
  if (!stored.refresh) return false;
  refreshInFlight ??= (async () => {
    try {
      const pair = await postJson<TokenPair>("/auth/refresh", {
        refresh_token: stored.refresh,
      });
      tokensFromBody(pair);
      return Boolean(loadAuth()?.access);
    } catch {
      store(null);
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/** api 层的请求助手：带 Authorization，401 时先刷新一次再重试。 */
export async function authedFetch(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<Response> {
  const stored = loadAuth();
  const headers = new Headers(init.headers);
  if (stored) headers.set("authorization", `Bearer ${stored.access}`);
  const response = await fetch(`${api}${path}`, { ...init, headers });
  if (response.status === 401 && retry && stored && (await tryRefresh(stored))) {
    const next = loadAuth();
    const retryHeaders = new Headers(init.headers);
    if (next) retryHeaders.set("authorization", `Bearer ${next.access}`);
    return fetch(`${api}${path}`, { ...init, headers: retryHeaders });
  }
  return response;
}

/** 下载文件：同源拿字节（307 直链跨域会被桶的 CORS 挡住），再交给浏览器普通下载。 */
export async function downloadFile(fileId: string, name?: string): Promise<void> {
  const response = await authedFetch(`/files/${fileId}/content`, {}, false);
  if (response.status === 401) {
    const stored = loadAuth();
    if (stored && (await tryRefresh(stored))) return downloadFile(fileId, name);
    throw new ApiError(401, "登录状态失效，请重新登录");
  }
  if (!response.ok) {
    throw errorFromResponse(response, await response.json().catch(() => null));
  }
  const blob = await response.blob();
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = name || "";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(anchor.href), 10_000);
}
