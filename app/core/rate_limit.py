"""认证等昂贵入口的固定窗口限流。

计数键用业务身份（规范化邮箱）而不是客户端 IP：服务跑在反向代理后面，真实来源
要靠 X-Forwarded-For 才拿得到，而那个头可伪造、是否可信又取决于部署；用邮箱既
不需要额外配置，也不会因为代理把所有用户挤进同一个桶里。

配了 Redis 时窗口计数放在 Redis，多 worker 看到的是同一份；没配就退回进程内
dict（本地开发与当前的单 worker 部署）。
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.exceptions import TooManyRequestsError

logger = logging.getLogger(__name__)

_REDIS_TIMEOUT_SECONDS = 2.0

# 进程内计数表的上限：防的是"拿随机邮箱刷注册"把内存顶爆
_MAX_WINDOWS = 10_000


@dataclass(slots=True)
class _Window:
    expires_at: float
    count: int = 0


class RateLimiter:
    """每个键在 window_seconds 内最多允许 limit 次。"""

    def __init__(self, *, redis_client: Redis | None = None, key_prefix: str = "pigeon") -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._windows: dict[str, _Window] = {}

    async def retry_after(self, key: str, limit: int, window_seconds: float) -> int:
        """放行返回 0；被限流返回还需要等多少秒。"""
        if self._redis is None:
            return self._local_retry_after(key, limit, window_seconds)
        return await self._redis_retry_after(self._redis, key, limit, window_seconds)

    async def enforce(self, action: str, key: str, limit: int, window_seconds: float) -> None:
        """超限就抛 429，把等待秒数带给前端；几个认证入口共用这一句文案。"""
        wait = await self.retry_after(key, limit, window_seconds)
        if wait:
            raise TooManyRequestsError(
                f"{action}尝试过于频繁，请 {wait} 秒后再试", retry_after=wait
            )

    def _local_retry_after(self, key: str, limit: int, window_seconds: float) -> int:
        now = time.monotonic()
        window = self._windows.get(key)
        if window is None or window.expires_at <= now:
            self._make_room(now)
            self._windows[key] = _Window(expires_at=now + window_seconds, count=1)
            return 0
        if window.count >= limit:
            return max(1, math.ceil(window.expires_at - now))
        window.count += 1
        return 0

    async def _redis_retry_after(
        self, redis: Redis, key: str, limit: int, window_seconds: float
    ) -> int:
        try:
            async with asyncio.timeout(_REDIS_TIMEOUT_SECONDS):
                window = max(1, math.ceil(window_seconds))
                name = self._key(key)
                count = int(await redis.incr(name))
                if count == 1:
                    await redis.expire(name, window)
                if count > limit:
                    remaining = int(await redis.ttl(name))
                    if remaining < 0:
                        # 只在 incr 与 expire 之间被硬杀才会没有 TTL；当场补上，别留一个死键
                        await redis.expire(name, window)
                        remaining = window
                    return max(1, remaining)
                return 0
        except Exception as exc:
            # Redis 挂了不应该让登录/注册一起挂；退回进程内窗口，至少保留单 worker 的限流。
            # 这里用 warning 不带堆栈：认证请求量大时避免刷爆日志。
            logger.warning("Rate limiter Redis backend failed; using process-local window: %s", exc)
            return self._local_retry_after(key, limit, window_seconds)

    def _key(self, suffix: str) -> str:
        return f"{self._prefix}:ratelimit:{suffix}"

    def _make_room(self, now: float) -> None:
        """键满了先清过期的；还是满就顶掉最快到期的那条，宁可少算也不要涨内存。"""
        if len(self._windows) < _MAX_WINDOWS:
            return
        for stale in [key for key, window in self._windows.items() if window.expires_at <= now]:
            del self._windows[stale]
        if len(self._windows) < _MAX_WINDOWS:
            return
        earliest = min(self._windows, key=lambda key: self._windows[key].expires_at)
        del self._windows[earliest]
