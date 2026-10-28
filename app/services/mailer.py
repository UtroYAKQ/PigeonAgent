"""SMTP 发件：标准库 smtplib 丢线程池，不引入额外依赖。

邮件发不出去不阻断注册（验证码已在库里，resend 也能走到），只留日志。
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)

CODE_SUBJECT = "PigeonAgent 邮箱验证码"


def code_body(code: str, minutes: int) -> str:
    return f"你的验证码是 {code}，{minutes} 分钟内有效。请勿转发给他人。"


def _send_sync(settings: Settings, to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    assert settings.smtp_host is not None
    if settings.smtp_tls == "ssl":
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=ssl.create_default_context()
        ) as smtp:
            _login_and_send(smtp, settings, message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            if settings.smtp_tls == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            _login_and_send(smtp, settings, message)


def _login_and_send(smtp: smtplib.SMTP, settings: Settings, message: EmailMessage) -> None:
    if settings.smtp_user and settings.smtp_password:
        smtp.login(settings.smtp_user, settings.smtp_password)
    smtp.send_message(message)


async def send_mail(settings: Settings, to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP 未配置，无法发信；检查 .env 里的 SMTP 配置")
    try:
        await asyncio.to_thread(_send_sync, settings, to_email, subject, body)
    except Exception:
        logger.warning(
            "Verification email to %s failed; the code stays valid in DB", to_email, exc_info=True
        )
