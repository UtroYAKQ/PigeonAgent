from typing import Any


class AppError(Exception):
    status_code = 500

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        # 结构化补充信息（如 409 的 active_run_id）随响应体一起下发；None 值不出现
        self.extra: dict[str, Any] = {
            key: value for key, value in extra.items() if value is not None
        }


class ConfigurationError(AppError):
    pass


class UnauthenticatedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class ConflictError(AppError):
    status_code = 409


class NotFoundError(AppError):
    status_code = 404


class GoneError(AppError):
    status_code = 410


class UnprocessableError(AppError):
    status_code = 422


class TooManyRequestsError(AppError):
    """窗口内尝试过多；retry_after 秒随响应体下发，前端可以直接倒计时。"""

    status_code = 429


class StorageError(AppError):
    """对象存储上游拒绝时统一成这一条，端点不必再认 botocore 的异常形状。"""

    status_code = 502


class StorageUnavailableError(AppError):
    """部署没配桶：这是服务侧暂不可用，不是调用方的错。"""

    status_code = 503


class MailDeliveryError(AppError):
    """SMTP 拒收/连不上；验证码仍在库里，但绝不能对前端说已发送。"""

    status_code = 502


class CreditsExhausted(Exception):
    """run 期间余额见底的停止信号，不是 HTTP 错误，所以不带状态码也不带文案。

    抛出方只表达「本轮该停」；错误码和用户可见文案由 `AgentTurn.summarize_error`
    统一归类，再落进 run 历史——一轮为什么结束只有一处说了算。
    """
