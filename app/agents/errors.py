"""模型异常到稳定错误码的归类；原始细节留在服务端日志。"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.exceptions import (
    ContentFilterError,
    IncompleteToolCall,
    ModelAPIError,
    ModelConnectionError,
    ModelContextWindowExceededError,
    ModelHTTPError,
    ModelOverloadedError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelRequestTimeout,
    ModelServerError,
    ModelTimeoutError,
    ModelUnavailableError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from app.core.exceptions import CreditsExhausted, describe_error


@dataclass(frozen=True, slots=True)
class ErrorSummary:
    code: str
    message: str
    retryable: bool


def _http_error_summary(exc: ModelHTTPError) -> ErrorSummary:
    status = exc.status_code
    if status in (401, 403):
        return ErrorSummary(
            "model_auth_error",
            "模型凭证无效或没有权限，请联系管理员检查 API Key。",
            False,
        )
    if status == 402:
        return ErrorSummary(
            "quota_exceeded",
            "模型供应商账户额度不足或已欠费，请联系管理员检查供应商账户。",
            False,
        )
    if status == 404:
        return ErrorSummary(
            "model_unavailable",
            "模型服务暂时不可用（模型下线或名称有误），请检查模型配置后重试。",
            True,
        )
    if status == 408:
        return ErrorSummary(
            "model_timeout",
            "模型响应超时，请稍后重试；长任务可以拆小后再试。",
            True,
        )
    if status == 429:
        return ErrorSummary(
            "rate_limited",
            "模型请求过于频繁，已被限流；请稍等片刻再重试。",
            True,
        )
    if status >= 500:
        return ErrorSummary(
            "model_server_error",
            "模型服务内部错误，请稍后重试。",
            True,
        )
    return ErrorSummary(
        "invalid_request",
        f"模型服务拒绝了这次请求（HTTP {status}），请检查模型配置或稍后重试。",
        False,
    )


def summarize_error(exc: BaseException) -> ErrorSummary:
    """把上游异常归类成稳定错误码 + 用户可执行的提示。"""
    raw = describe_error(exc, limit=2000)

    if isinstance(exc, IncompleteToolCall) or "exceeded max retries count of" in raw:
        return ErrorSummary(
            "tool_arguments_incomplete",
            "模型生成的工具参数不完整，通常是单次输出过长被截断。请重试；内容较长时让它分段生成。",
            True,
        )
    if isinstance(exc, UsageLimitExceeded):
        return ErrorSummary(
            "usage_limit_exceeded",
            "本轮调用轮次超过上限，生成已停止；请重试，或把任务拆成多步。",
            False,
        )
    if isinstance(exc, CreditsExhausted):
        return ErrorSummary(
            "credits_exhausted",
            "积分已用尽，本轮对话已停止；请联系管理员充值后重试。",
            False,
        )
    if isinstance(exc, ModelContextWindowExceededError):
        return ErrorSummary(
            "context_window_exceeded",
            "上下文超出模型窗口，请压缩历史或调大上下文窗口后重试。",
            False,
        )
    if isinstance(exc, ModelQuotaExceededError):
        return ErrorSummary(
            "quota_exceeded",
            "模型供应商账户额度不足或已欠费，请联系管理员检查供应商账户。",
            False,
        )
    if isinstance(exc, ModelRateLimitError):
        return ErrorSummary(
            "rate_limited",
            "模型请求过于频繁，已被限流；请稍等片刻再重试。",
            True,
        )
    if isinstance(exc, ModelOverloadedError):
        return ErrorSummary(
            "model_overloaded",
            "模型服务当前繁忙，请稍后重试。",
            True,
        )
    if isinstance(exc, ModelUnavailableError):
        return ErrorSummary(
            "model_unavailable",
            "模型服务暂时不可用（模型下线或名称有误），请检查模型配置后重试。",
            True,
        )
    if isinstance(exc, (ModelRequestTimeout, ModelTimeoutError)):
        return ErrorSummary(
            "model_timeout",
            "模型响应超时，请稍后重试；长任务可以拆小后再试。",
            True,
        )
    if isinstance(exc, ModelConnectionError):
        return ErrorSummary(
            "model_connection",
            "无法连接模型服务，请检查网络、API 地址或代理设置后重试。",
            True,
        )
    if isinstance(exc, ModelServerError):
        return ErrorSummary(
            "model_server_error",
            "模型服务内部错误，请稍后重试。",
            True,
        )
    if isinstance(exc, ModelHTTPError):
        return _http_error_summary(exc)
    if isinstance(exc, ContentFilterError):
        return ErrorSummary(
            "content_filter",
            "内容被模型安全策略拦截，请调整提问后重试。",
            False,
        )
    if isinstance(exc, ModelAPIError):
        return ErrorSummary(
            "model_api_error",
            "模型调用失败，请稍后重试。",
            True,
        )
    if isinstance(exc, UnexpectedModelBehavior):
        return ErrorSummary(
            "unexpected_model_behavior",
            "模型返回了无法处理的结果，请重试。",
            True,
        )
    return ErrorSummary(
        type(exc).__name__,
        "生成失败，请稍后重试。",
        isinstance(exc, RETRYABLE_ERRORS),
    )


RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    ModelConnectionError,
    ModelTimeoutError,
    ModelRateLimitError,
    ModelOverloadedError,
    ModelUnavailableError,
    ModelServerError,
    UnexpectedModelBehavior,
)
