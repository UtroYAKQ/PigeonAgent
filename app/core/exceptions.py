class AppError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConfigurationError(AppError):
    pass


class UnauthenticatedError(AppError):
    status_code = 401


class ConflictError(AppError):
    status_code = 409


class NotFoundError(AppError):
    status_code = 404


class GoneError(AppError):
    status_code = 410


class UnprocessableError(AppError):
    status_code = 422


class StorageError(AppError):
    """对象存储上游拒绝时统一成这一条，端点不必再认 botocore 的异常形状。"""

    status_code = 502


class StorageUnavailableError(AppError):
    """部署没配桶：这是服务侧暂不可用，不是调用方的错。"""

    status_code = 503
