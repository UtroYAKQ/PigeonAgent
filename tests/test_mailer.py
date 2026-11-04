"""SMTP 发信：发件人回落与失败上报。"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

from app.core.config import Settings
from app.infra import mailer
from tests.conftest import TEST_SECRET_KEY


class _FakeSMTP:
    def __init__(self, host: str, port: int) -> None:
        self.sent: list[Any] = []
        self.logged_in: tuple[str, str] | None = None

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


def _settings(**overrides: Any) -> Settings:
    base = dict(
        secret_key=TEST_SECRET_KEY,
        smtp_host="stub",
        smtp_port=2525,
        smtp_tls="none",
        smtp_user="me@example.com",
        smtp_password="app-password",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def test_sender_is_the_smtp_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务商要求 MAIL FROM 等于授权用户，否则 501。"""
    fake = _FakeSMTP("stub", 2525)
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: fake)

    assert await mailer.send_mail(_settings(), "to@example.com", "主题", "正文") is True
    assert fake.logged_in == ("me@example.com", "app-password")
    assert fake.sent[0]["From"] == "me@example.com"
    assert fake.sent[0]["To"] == "to@example.com"


async def test_explicit_sender_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSMTP("stub", 2525)
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: fake)

    settings = _settings(email_from="PigeonAgent <hi@example.com>")
    assert await mailer.send_mail(settings, "to@example.com", "主题", "正文") is True
    assert fake.sent[0]["From"] == "PigeonAgent <hi@example.com>"


async def test_failure_is_reported_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Refusing(_FakeSMTP):
        def send_message(self, message: Any) -> None:
            raise smtplib.SMTPSenderRefused(501, b"Mail from address must be same as auth", "x")

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: _Refusing("stub", 2525))
    assert await mailer.send_mail(_settings(), "to@example.com", "主题", "正文") is False


async def test_missing_host_raises() -> None:
    with pytest.raises(RuntimeError):
        await mailer.send_mail(_settings(smtp_host=None), "to@example.com", "主题", "正文")


async def test_send_is_time_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """端口填错或出网被挡时，必须在设定的秒数里放弃，不能把注册挂到内核超时。"""
    seen: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> _FakeSMTP:
        seen.clear()
        seen.update(args=args, **kwargs)
        return _FakeSMTP("stub", 2525)

    monkeypatch.setattr(smtplib, "SMTP", capture)
    assert await mailer.send_mail(_settings(), "to@example.com", "主题", "正文") is True
    assert seen["timeout"] == 20

    monkeypatch.setattr(smtplib, "SMTP_SSL", capture)
    settings = _settings(smtp_tls="ssl", smtp_timeout_seconds=5)
    assert await mailer.send_mail(settings, "to@example.com", "主题", "正文") is True
    assert seen["timeout"] == 5
