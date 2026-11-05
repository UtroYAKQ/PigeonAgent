"""S3 兼容对象存储：AWS S3、阿里云 OSS、MinIO、RustFS 共用同一套 API。

只有 boto3 的同步客户端碰网络，全部丢进线程池，别堵住事件循环。
key 由调用方拼，这一层不掺业务；没配置就明确报错，不静默退回本地磁盘。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings
from app.core.exceptions import StorageError, StorageUnavailableError

if TYPE_CHECKING:
    # 只在类型检查期引入：mypy-boto3-s3 是 dev 依赖，运行时不该要求安装
    from mypy_boto3_s3 import S3Client

# \w 带 Unicode：中文文件名不能被当成非法字符抹掉；分隔符和控制字符才要清掉
_UNSAFE = re.compile(r"[^\w.-]+", re.UNICODE)
_MAX_NAME_CHARS = 120
_T = TypeVar("_T")


def safe_name(filename: str | None) -> str:
    """只留一个能安全拼进 key 的文件名：去掉目录、路径穿越和控制字符。"""
    tail = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("_", tail).strip("._")
    return (cleaned or "file")[:_MAX_NAME_CHARS]


def upload_key(prefix: str) -> str:
    """上传区临时 key：<prefix>/tmp-uploads/<uuid32>；内容寻址之前先落在它下面。"""
    root = "/".join(part for part in (prefix.strip("/"), "tmp-uploads") if part)
    return f"{root}/{uuid.uuid4().hex}"


@dataclass(frozen=True)
class PutResult:
    key: str
    size: int


class ObjectStorage(Protocol):
    """对象存储的最小动作集；换实现不用动调用方。"""

    async def put(self, key: str, body: bytes, content_type: str | None) -> PutResult: ...

    async def head(self, key: str) -> PutResult | None: ...

    async def get(self, key: str) -> bytes: ...

    async def copy(self, source: str, target: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def url_for(
        self,
        key: str,
        *,
        download_name: str | None = None,
        inline: bool = False,
        content_type: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str: ...

    async def presign_put(self, key: str, *, content_length: int) -> str: ...


def _build_client(settings: Settings, *, endpoint_url: str | None = None) -> S3Client:
    if not settings.s3_bucket:
        raise StorageUnavailableError("对象存储未启用：配置 S3_BUCKET 后重试")
    if not (settings.s3_access_key and settings.s3_secret_key):
        raise StorageUnavailableError("对象存储需要 S3_ACCESS_KEY 与 S3_SECRET_KEY")
    # 不显式给凭证时 boto3 会去摸环境变量和 IMDS，容器里首帧能卡好几秒
    session = boto3.session.Session(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    return session.client(
        "s3",
        endpoint_url=endpoint_url if endpoint_url is not None else settings.s3_endpoint_url,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.s3_addressing_style},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _content_disposition(name: str, *, inline: bool = False) -> str:
    """RFC 5987：UTF-8 名走 filename*，filename 兜底用百分号编码，别坑浏览器。"""
    encoded = quote(name, safe="")
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename=\"{encoded}\"; filename*=UTF-8''{encoded}"


class S3Storage:
    def __init__(self, settings: Settings, client: S3Client | None = None) -> None:
        if not settings.s3_bucket:
            raise StorageUnavailableError("对象存储未启用：配置 S3_BUCKET 后重试")
        self.bucket = settings.s3_bucket
        self.ttl_seconds = settings.s3_presign_ttl_seconds
        self._client = client or _build_client(settings)
        # 预签名虽然只在本地算，但 Host 会写进签名；容器内网 endpoint 和浏览器
        # 可达的公网地址不同时，必须用公网地址单独建一个 client。
        public = (settings.s3_public_endpoint_url or "").strip()
        if client is None and public and public != (settings.s3_endpoint_url or ""):
            self._presign_client = _build_client(settings, endpoint_url=public)
        else:
            self._presign_client = self._client

    async def _run(self, action: Callable[..., _T], **kwargs: Any) -> _T:
        try:
            return await asyncio.to_thread(action, **kwargs)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "unknown")
            raise StorageError(f"对象存储调用失败：{code}") from error

    async def put(self, key: str, body: bytes, content_type: str | None) -> PutResult:
        args: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": body}
        if content_type:
            args["ContentType"] = content_type
        await self._run(self._client.put_object, **args)
        return PutResult(key=key, size=len(body))

    async def head(self, key: str) -> PutResult | None:
        """对象缺失返回 None，其余上游错误照旧翻成 StorageError。"""
        try:
            response = await asyncio.to_thread(
                self._client.head_object, Bucket=self.bucket, Key=key
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StorageError(f"对象存储调用失败：{code or 'unknown'}") from error
        size = int(response.get("ContentLength") or 0)
        return PutResult(key=key, size=size)

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await self._run(_read)

    async def copy(self, source: str, target: str) -> None:
        await self._run(
            self._client.copy_object,
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": source},
            Key=target,
        )

    async def delete(self, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=self.bucket, Key=key)

    def _signed_url(
        self,
        key: str,
        download_name: str | None,
        *,
        inline: bool = False,
        content_type: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = _content_disposition(
                download_name, inline=inline
            )
        # 上传走 presign 时没带 Content-Type，媒体直链靠这里把类型补回去
        if content_type:
            params["ResponseContentType"] = content_type
        # 预签名只是本地算签名，不发请求
        return self._presign_client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=ttl_seconds or self.ttl_seconds
        )

    async def url_for(
        self,
        key: str,
        *,
        download_name: str | None = None,
        inline: bool = False,
        content_type: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """短时效 GET 签名是唯一的取出路径；inline 给 <img>/<video> 直接渲染。"""
        return self._signed_url(
            key,
            safe_name(download_name) if download_name else None,
            inline=inline,
            content_type=content_type,
            ttl_seconds=ttl_seconds,
        )

    async def presign_put(self, key: str, *, content_length: int) -> str:
        """给客户端直达上传区的 PUT 签名，并把声明大小纳入签名约束。"""
        return self._presign_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentLength": content_length},
            ExpiresIn=self.ttl_seconds,
        )


_storages: dict[str, ObjectStorage] = {}


def get_storage() -> ObjectStorage:
    """FastAPI 依赖；按 bucket+endpoint 复用客户端，配置换了才重建。"""
    settings = get_settings()
    fingerprint = f"{settings.s3_bucket}|{settings.s3_endpoint_url}"
    storage = _storages.get(fingerprint)
    if storage is None:
        storage = S3Storage(settings)
        _storages[fingerprint] = storage
    return storage
