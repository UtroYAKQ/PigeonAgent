"""自由文本里的凭据擦除。

结构化 body 走 operation_log.scrub 的"按 key 名脱敏"；但被截断的 body、非 JSON
的 body、以及上游异常原文都是裸文本，key 名规则管不到，只能按形态识别。
落库或回显给用户/模型之前，裸文本一律先过 redact_text。
"""

import re

# "api_key": "sk-..." / "password" : "..." 之类，只换值不换结构
_JSON_FIELD = re.compile(
    r'(?i)("[^"]*(?:password|passwd|secret|token|api[_-]?key|authorization|access[_-]?key)'
    r'[^"]*"\s*:\s*)"[^"]*"'
)
# URL 查询串里的 ?api_key=xxx / &key=xxx
_QUERY_PARAM = re.compile(r"(?i)([?&](?:api[_-]?key|key|access[_-]?key|token|secret)=)[^&\s\"']+")
# 常见厂商的密钥前缀形态：sk-xxx / pk-xxx
_KEY_PREFIX = re.compile(r"\b(?:sk|pk|ak|sa)-[A-Za-z0-9_\-]{6,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{8,}=*")


def redact_text(value: str) -> str:
    """把裸文本里能认出身份的凭据替换成 ***；认不出的原样保留，宁可漏不可错删。"""
    redacted = _JSON_FIELD.sub(r'\1"***"', value)
    redacted = _QUERY_PARAM.sub(r"\1***", redacted)
    redacted = _KEY_PREFIX.sub("***", redacted)
    return _BEARER.sub("Bearer ***", redacted)
