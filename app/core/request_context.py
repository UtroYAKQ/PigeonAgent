"""请求上下文：request id、操作日志采集和通用安全响应头。"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders

from app.core.operation import OperationEvent, OperationSink

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("app.request")

_JSON_TYPES = {"application/json"}


@dataclass(slots=True)
class RequestOperationContext:
    logger: OperationSink | None
    request_id: str


_operation_context: ContextVar[RequestOperationContext | None] = ContextVar(
    "operation_context", default=None
)


def current_operation_context() -> RequestOperationContext | None:
    return _operation_context.get()


def _is_json(headers: MutableHeaders) -> bool:
    content_type = (headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return content_type in _JSON_TYPES or content_type.endswith("+json")


def _content_length(headers: MutableHeaders) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _query(scope: Any) -> dict[str, Any]:
    raw = scope.get("query_string", b"")
    if not raw:
        return {}
    parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


def _client_ip(scope: Any, headers: MutableHeaders, trust_proxy: bool) -> str | None:
    if trust_proxy:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:64]
    client = scope.get("client")
    if client:
        return str(client[0])[:64]
    return None


async def _capture_request(
    scope: Any,
    receive: Callable[[], Awaitable[dict[str, Any]]],
    headers: MutableHeaders,
    max_bytes: int,
) -> tuple[Callable[[], Awaitable[dict[str, Any]]], bytes | None, int, bool]:
    """只缓存小体积 JSON 请求体；预览请求照常透传，不改变 FastAPI 读取行为。"""
    if scope.get("method") in {"GET", "HEAD", "OPTIONS"} or not _is_json(headers):
        return receive, None, _content_length(headers) or 0, False
    length = _content_length(headers)
    if length is None or length == 0 or max_bytes <= 0 or length > max_bytes:
        return receive, None, length or 0, length is not None and length > max_bytes

    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return receive, None, 0, False
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    raw = b"".join(chunks)
    replayed = False

    async def replay() -> dict[str, Any]:
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return await receive()

    return replay, raw, len(raw), len(raw) > max_bytes


class RequestContextMiddleware:
    """纯 ASGI 中间件：采集请求/响应并异步投递操作日志。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        request_id = headers.get("x-request-id") or uuid.uuid4().hex
        app = scope.get("app")
        logger_: OperationSink | None = getattr(
            getattr(app, "state", None), "operation_logger", None
        )
        path = str(scope.get("path") or "")
        excluded = logger_ is not None and not logger_.should_log(path)
        started = time.perf_counter()
        status = 500
        response_type = ""
        response_buffer = bytearray()
        response_bytes = 0
        response_truncated = False
        capture_response = False
        max_request = logger_.settings.operation_log_max_request_body if logger_ else 0
        max_response = logger_.settings.operation_log_max_response_body if logger_ else 0
        trust_proxy = logger_.settings.operation_log_trust_proxy if logger_ else False

        if logger_ is not None and not excluded and logger_.enabled:
            receive, request_body, request_bytes, request_truncated = await _capture_request(
                scope, receive, headers, max_request
            )
        else:
            request_body = None
            request_bytes = _content_length(headers) or 0
            request_truncated = False

        state = scope.setdefault("state", {})
        context_token: Token[RequestOperationContext | None] = _operation_context.set(
            RequestOperationContext(
                logger=None if excluded else logger_,
                request_id=request_id,
            )
        )

        async def send_with_headers(message: Any) -> None:
            nonlocal status, response_type, response_bytes, response_truncated
            nonlocal capture_response
            if message["type"] == "http.response.start":
                status = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers.setdefault("X-Request-ID", request_id)
                response_headers.setdefault("X-Content-Type-Options", "nosniff")
                response_type = response_headers.get("content-type") or ""
                capture_response = (
                    logger_ is not None
                    and not excluded
                    and logger_.enabled
                    and _is_json(response_headers)
                )
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                response_bytes += len(chunk)
                if capture_response and len(response_buffer) < max_response:
                    remaining = max_response - len(response_buffer)
                    response_buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        response_truncated = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            status = 500
            raise
        finally:
            _operation_context.reset(context_token)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            actor_id = state.get("operation_actor_id")
            actor_email = state.get("operation_actor_email")
            route = getattr(scope.get("route"), "path", None)
            if logger_ is not None and not excluded:
                logger_.submit(
                    OperationEvent(
                        request_id=request_id,
                        kind="request",
                        actor_id=actor_id if isinstance(actor_id, uuid.UUID) else None,
                        actor_email=str(actor_email) if actor_email else None,
                        method=str(scope.get("method") or ""),
                        path=path,
                        route=str(route) if route else path,
                        query=_query(scope),
                        request_body=request_body,
                        request_bytes=request_bytes,
                        request_truncated=request_truncated,
                        status_code=status,
                        response_body=bytes(response_buffer) if capture_response else None,
                        response_bytes=response_bytes,
                        response_truncated=response_truncated,
                        duration_ms=elapsed_ms,
                        client_ip=_client_ip(scope, headers, trust_proxy),
                        user_agent=(headers.get("user-agent") or "")[:512] or None,
                    )
                )
            logger.info(
                "%s %s -> %s %.1fms rid=%s %s",
                scope.get("method"),
                path,
                status,
                elapsed_ms,
                request_id,
                response_type.split(";", 1)[0],
            )
