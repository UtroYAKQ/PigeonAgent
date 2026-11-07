"""同源媒体直链的窗口与校验规则。"""

from __future__ import annotations

from uuid import uuid4

from app.services.file_service import link as file_link

SECRET = "unit-test-secret"


def test_expiry_lands_on_a_window_boundary() -> None:
    now = 1_700_000_123.4
    ttl = 600
    expires_at = file_link.window_expiry(now, ttl)

    assert expires_at % ttl == 0
    # 链接至少还能用满一个窗口，最多两个，避免刚签出来就贴着过期线
    assert ttl <= expires_at - now <= 2 * ttl


def test_same_window_issues_the_same_link() -> None:
    ttl = 600
    file_id = uuid4()
    start = 1_700_000_400.0

    first = file_link.issue(SECRET, file_id, ttl, now=start)
    later = file_link.issue(SECRET, file_id, ttl, now=start + 300)

    # URL 稳定是浏览器缓存命中的前提
    assert first == later


def test_verify_rejects_other_file_tampering_expiry_and_secret() -> None:
    file_id = uuid4()
    expires_at, token = file_link.issue(SECRET, file_id, 600, now=1_700_000_400.0)

    assert file_link.verify(SECRET, file_id, expires_at, token, now=1_700_000_500.0)
    assert not file_link.verify(SECRET, uuid4(), expires_at, token, now=1_700_000_500.0)
    assert not file_link.verify(SECRET, file_id, expires_at, "0" * len(token), now=1_700_000_500.0)
    assert not file_link.verify("other-secret", file_id, expires_at, token, now=1_700_000_500.0)
    assert not file_link.verify(SECRET, file_id, expires_at, token, now=float(expires_at) + 1)
