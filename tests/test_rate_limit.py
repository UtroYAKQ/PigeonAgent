"""限流的窗口语义：进程内与 Redis 两种后端要给出同一套结论。"""

import asyncio

from fakeredis import FakeAsyncRedis

from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import RateLimiter

KEY = "login:user@example.com"
LIMIT = 3


async def test_local_window_blocks_then_resets() -> None:
    limiter = RateLimiter()
    for _ in range(LIMIT):
        assert await limiter.retry_after(KEY, LIMIT, 0.2) == 0
    assert await limiter.retry_after(KEY, LIMIT, 0.2) >= 1

    await asyncio.sleep(0.25)
    assert await limiter.retry_after(KEY, LIMIT, 0.2) == 0


async def test_redis_window_is_shared_across_workers() -> None:
    """两个 limiter 实例共用一个 Redis，等价于两个 worker 进程看到同一份计数。"""
    client = FakeAsyncRedis()
    worker_a = RateLimiter(redis_client=client)
    worker_b = RateLimiter(redis_client=client)

    assert await worker_a.retry_after(KEY, LIMIT, 60) == 0
    assert await worker_b.retry_after(KEY, LIMIT, 60) == 0
    assert await worker_a.retry_after(KEY, LIMIT, 60) == 0
    # 第 4 次由哪个 worker 发起都要被挡：额度是全局的，不是每进程一份
    assert await worker_b.retry_after(KEY, LIMIT, 60) >= 1


async def test_redis_window_ttl_is_set_by_the_first_hit_only() -> None:
    """后续命中不能给键续期，否则持续请求会把窗口越拉越长，永远解不开。"""
    client = FakeAsyncRedis()
    limiter = RateLimiter(redis_client=client, key_prefix="test-window")
    name = f"test-window:ratelimit:{KEY}"

    assert await limiter.retry_after(KEY, LIMIT, 60) == 0
    ttl_after_first = int(await client.ttl(name))
    assert await limiter.retry_after(KEY, LIMIT, 60) == 0
    assert int(await client.ttl(name)) == ttl_after_first


async def test_redis_backfills_a_missing_ttl() -> None:
    """进程在 incr 与 expire 之间被硬杀会留下没有 TTL 的键；超限时要当场补上而不是永久锁死。"""
    client = FakeAsyncRedis()
    limiter = RateLimiter(redis_client=client, key_prefix="test-ttl")
    name = f"test-ttl:ratelimit:{KEY}"
    await client.set(name, LIMIT)  # 已到上限且没有过期时间

    assert await limiter.retry_after(KEY, LIMIT, 60) >= 1
    assert int(await client.ttl(name)) > 0


async def test_enforce_names_the_action_in_429() -> None:
    limiter = RateLimiter()
    await limiter.enforce("登录", KEY, 1, 60)
    try:
        await limiter.enforce("登录", KEY, 1, 60)
    except TooManyRequestsError as error:
        assert error.status_code == 429
        assert "登录" in error.detail
        assert error.extra["retry_after"] > 0
    else:
        raise AssertionError("超出窗口上限应当抛 429")
