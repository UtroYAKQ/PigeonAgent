"""SMTP 发件：标准库 smtplib 丢线程池，不引入额外依赖。

每次连接与发信都受 `smtp_timeout_seconds` 约束：端口写错或出网被挡时，
内核的 SYN 重试可以等到两百多秒，而这段代码正跑在注册请求的同步链上。
失败只在这里留日志并回 False，由调用方决定怎么处理——验证码仍在库里。
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
    # 发件人必须跟 SMTP 登录账号一致，否则多数服务商直接 501
    message["From"] = settings.sender_address
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    timeout = settings.smtp_timeout_seconds
    assert settings.smtp_host is not None
    if settings.smtp_tls == "ssl":
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as smtp:
            _login_and_send(smtp, settings, message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout) as smtp:
            if settings.smtp_tls == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            _login_and_send(smtp, settings, message)


def _login_and_send(smtp: smtplib.SMTP, settings: Settings, message: EmailMessage) -> None:
    if settings.smtp_user and settings.smtp_password:
        smtp.login(settings.smtp_user, settings.smtp_password)
    smtp.send_message(message)


async def send_mail(settings: Settings, to_email: str, subject: str, body: str) -> bool:
    """发信；返回是否真的发出去。

    失败只留日志由调用方决定怎么处理：验证码仍在库里，但绝不能对前端说
    "已发送"——那样用户会一直等一封永远不来的信。
    """
    if not settings.smtp_host:
        raise RuntimeError("SMTP 未配置，无法发信；检查 .env 里的 SMTP 配置")
    try:
        await asyncio.to_thread(_send_sync, settings, to_email, subject, body)
    except Exception:
        logger.warning(
            "Verification email to %s failed; the code stays valid in DB", to_email, exc_info=True
        )
        return False
    return True
