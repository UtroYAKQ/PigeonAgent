/** 带 HTTP 状态码的接口错误；message 取自 FastAPI 的 detail。 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** run 的 SSE 队列已被摘除：run 跑得比订阅快，或历史被清理。 */
export class RunGoneError extends Error {
  constructor() {
    super("run stream is gone");
    this.name = "RunGoneError";
  }
}

export function errorMessage(cause: unknown): string {
  // fetch 断网只在浏览器里报这句英文，直接展示对用户没意义
  if (cause instanceof TypeError && /fetch/i.test(cause.message)) {
    return "网络请求失败，请检查后端连接";
  }
  return cause instanceof Error ? cause.message : String(cause);
}

/** FastAPI 的错误体是 {detail: string | object}；拿不到就退回状态行。 */
export function errorFromResponse(response: Response, body?: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  const message =
    typeof detail === "string"
      ? detail
      : detail != null
        ? JSON.stringify(detail)
        : `${response.status} ${response.statusText}`;
  return new ApiError(response.status, message);
}
