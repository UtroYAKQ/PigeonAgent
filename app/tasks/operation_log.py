"""异步操作日志：请求链路只入队，后台批量写入数据库。"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.operation import OperationEvent
from app.core.redaction import redact_text
from app.models.operation_log import OperationLog

logger = logging.getLogger(__name__)

_MAX_STRING = 2_000
_MAX_ITEMS = 50
_MAX_DEPTH = 6
_RETENTION_BATCH = 5_000
_RETENTION_INTERVAL_SECONDS = 3_600
_WRITE_ATTEMPTS = 3

_SENSITIVE_SUFFIXES = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "access_key",
    "private_key",
    "authorization",
    "cookie",
)
_SENSITIVE_KEYS = {"code", "otp", "verification_code", "email_code"}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized == suffix or normalized.endswith(f"_{suffix}") for suffix in _SENSITIVE_SUFFIXES
    )


def scrub(value: Any, *, depth: int = 0) -> Any:
    """递归脱敏并截断；body 再大也不会把整份内容写进日志。"""
    if depth > _MAX_DEPTH:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        loc = value.get("loc")
        redact_input = isinstance(loc, list) and any(_is_sensitive_key(str(part)) for part in loc)
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                result["_truncated"] = True
                break
            text_key = str(key)
            if redact_input and text_key == "input":
                result[text_key] = "***"
            else:
                result[text_key] = (
                    "***" if _is_sensitive_key(text_key) else scrub(item, depth=depth + 1)
                )
        return result
    if isinstance(value, (list, tuple)):
        result_list = [scrub(item, depth=depth + 1) for item in value[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            result_list.append("[truncated]")
        return result_list
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else f"{value[:_MAX_STRING]}…"
    if isinstance(value, (bytes, bytearray)):
        return "[binary]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STRING]


def _json_body(raw: bytes | None, *, truncated: bool) -> Any:
    if raw is None:
        return None
    if truncated:
        # 截断后无法按 JSON 结构脱敏，只能按形态擦一遍裸文本
        text = redact_text(raw.decode("utf-8", errors="replace"))
        return {"_truncated": True, "preview": text[:_MAX_STRING]}
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redact_text(raw.decode("utf-8", errors="replace"))[:_MAX_STRING]
    return scrub(parsed)


class OperationLogger:
    """有界队列 + 批量写入；日志失败不影响业务请求。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._queue: asyncio.Queue[OperationEvent] = asyncio.Queue(
            maxsize=settings.operation_log_queue_max
        )
        self._worker: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._closed = False
        self.dropped = 0
        self.write_errors = 0

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def is_enabled(self) -> bool:
        return self._settings.operation_log_enabled

    def configure(self, settings: Settings) -> None:
        self._settings = settings
        if settings.operation_log_retention_days > 0:
            self._ensure_retention_task()

    def should_log(self, path: str) -> bool:
        if not self.is_enabled:
            return False
        excludes = [
            item.strip().rstrip("/")
            for item in self._settings.operation_log_exclude_paths.split(",")
            if item.strip()
        ]
        return not any(
            fnmatch.fnmatchcase(path, item) or ("*" not in item and path.startswith(f"{item}/"))
            for item in excludes
        )

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run_worker())
        self._ensure_retention_task()

    def submit(self, event: OperationEvent) -> None:
        if not self.is_enabled:
            return
        if event.kind == "request" and (not event.path or not self.should_log(event.path)):
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                logger.warning("Operation log queue is full; dropped %d entries", self.dropped)

    def submit_admin(
        self,
        *,
        actor: Any = None,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.submit(
            OperationEvent(
                request_id=request_id,
                kind="admin",
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", None),
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
            )
        )

    async def flush(self) -> None:
        if self._worker is not None and not self._closed:
            await self._queue.join()

    async def aclose(self) -> None:
        self._closed = True
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=5)
            except TimeoutError:
                logger.warning("Operation log queue did not drain within 5s")
            self._worker.cancel()
            with_drain = [self._worker]
            await asyncio.gather(*with_drain, return_exceptions=True)
        if self._retention_task is not None:
            self._retention_task.cancel()
            await asyncio.gather(self._retention_task, return_exceptions=True)
            self._retention_task = None

    def _ensure_retention_task(self) -> None:
        if self._settings.operation_log_retention_days <= 0 or self._retention_task is not None:
            return
        self._retention_task = asyncio.create_task(self._run_retention())

    async def _run_worker(self) -> None:
        while True:
            first = await self._queue.get()
            batch = [first]
            deadline = asyncio.get_running_loop().time() + (
                self._settings.operation_log_flush_ms / 1000
            )
            while len(batch) < self._settings.operation_log_batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), timeout))
                except TimeoutError:
                    break
            try:
                await self._write_batch(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _write_batch(self, batch: list[OperationEvent]) -> None:
        for attempt in range(_WRITE_ATTEMPTS):
            try:
                async with self._factory() as db:
                    await db.execute(
                        insert(OperationLog),
                        [self._row(event) for event in batch],
                    )
                    await db.commit()
                return
            except Exception:
                self.write_errors += 1
                if attempt == _WRITE_ATTEMPTS - 1:
                    logger.exception(
                        "Failed to persist %d operation log rows; dropping batch", len(batch)
                    )
                    return
                await asyncio.sleep(0.5 * (attempt + 1))

    def _request_body(self, event: OperationEvent) -> Any:
        body = _json_body(event.request_body, truncated=event.request_truncated)
        # 配置接口的密钥是 {"value": "..."}，key 本身是路径参数，必须单独识别
        if (
            event.path
            and event.path.startswith("/api/v1/configs/")
            and isinstance(body, dict)
            and "value" in body
        ):
            from app.core.config_specs import SPEC_BY_KEY

            spec = SPEC_BY_KEY.get(event.path.rsplit("/", 1)[-1])
            if spec is not None and spec.is_secret:
                body["value"] = "***"
        return body

    def _row(self, event: OperationEvent) -> dict[str, Any]:
        return {
            "request_id": event.request_id,
            "kind": event.kind,
            "actor_id": event.actor_id,
            "actor_email": event.actor_email,
            "method": event.method,
            "path": event.path,
            "route": event.route,
            "query": scrub(event.query) if event.query is not None else None,
            "request_body": self._request_body(event),
            "status_code": event.status_code,
            "response_body": _json_body(event.response_body, truncated=event.response_truncated),
            "duration_ms": event.duration_ms,
            "request_bytes": event.request_bytes,
            "response_bytes": event.response_bytes,
            "request_truncated": event.request_truncated,
            "response_truncated": event.response_truncated,
            "client_ip": event.client_ip,
            "user_agent": event.user_agent,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "detail": scrub(event.detail) if event.detail is not None else None,
            "created_at": event.created_at,
        }

    async def _run_retention(self) -> None:
        while True:
            await asyncio.sleep(_RETENTION_INTERVAL_SECONDS)
            try:
                await self._cleanup()
            except Exception:
                logger.exception("Operation log retention cleanup failed")

    async def _cleanup(self) -> None:
        days = self._settings.operation_log_retention_days
        if days <= 0:
            return
        cutoff = datetime.now(UTC) - timedelta(days=days)
        for _ in range(10):
            async with self._factory() as db:
                ids = list(
                    (
                        await db.scalars(
                            select(OperationLog.id)
                            .where(OperationLog.created_at < cutoff)
                            .limit(_RETENTION_BATCH)
                        )
                    ).all()
                )
                if not ids:
                    return
                await db.execute(delete(OperationLog).where(OperationLog.id.in_(ids)))
                await db.commit()
