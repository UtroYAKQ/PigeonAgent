"""邮箱格式校验：所有会触发验证码邮件的入口都在这里过一遍。

用 email-validator 处理常规地址（IDN、长度、标签规则），自建部署常见的
.local / localhost 等内网域名在包内被当成保留域名拒绝，这里补一份同样严格的
本地规则，避免默认管理员和内网 SMTP 用法被误伤。只做格式校验，不做 DNS 查询。
"""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

_INTERNAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
_LOCAL_PART = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_INVALID_MESSAGE = "请输入有效的邮箱地址"


def _is_internal_domain(domain: str) -> bool:
    return domain == "localhost" or domain.endswith(_INTERNAL_SUFFIXES)


def _is_valid_tld(domain: str) -> bool:
    """必须至少有一个点，且顶级域不是单个字符或纯数字。"""
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    tld = labels[-1]
    if len(tld) < 2:
        return False
    return tld.startswith("xn--") or tld.isalpha()


def _validate_internal(value: str) -> str:
    """内网域名走本地规则；结构要求与公网地址一致，只是不要求可注册 TLD。"""
    local, domain = value.rsplit("@", 1)
    if not 1 <= len(local) <= 64 or not _LOCAL_PART.fullmatch(local):
        raise ValueError(_INVALID_MESSAGE)
    labels = domain.split(".")
    if len(domain) > 253 or not all(_DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError(_INVALID_MESSAGE)
    if not _is_valid_tld(domain):
        raise ValueError(_INVALID_MESSAGE)
    return f"{local}@{domain}".lower()


def validated_email(raw: str) -> str:
    """返回规范化后的邮箱；格式不合法时抛出中文 ValueError 给 Pydantic。"""
    value = raw.strip()
    if not value or len(value) > 254:
        raise ValueError(_INVALID_MESSAGE)

    try:
        normalized = validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        domain = value.rsplit("@", 1)[-1].lower() if "@" in value else ""
        if not _is_internal_domain(domain):
            raise ValueError(_INVALID_MESSAGE) from None
        return _validate_internal(value)

    normalized = normalized.lower()
    domain = normalized.rsplit("@", 1)[-1]
    # email-validator 不做 DNS，单字符和数字 TLD 也会通过；在发信前收紧。
    if not _is_valid_tld(domain):
        raise ValueError(_INVALID_MESSAGE)
    return normalized
