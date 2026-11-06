import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.core.config import Settings
from app.core.exceptions import ConfigurationError, ForbiddenError, UnprocessableError
from app.domain.media_type import effective_media_type
from app.infra.storage import ObjectStorage, get_storage
from app.schemas.file import FileLinkOut, FilePrepare, FilePrepareOut, FileRead
from app.services import file_link, file_service

router = APIRouter(prefix="/files", tags=["files"])

StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
FileIdPath = Annotated[uuid.UUID, Path(description="逻辑文件 id")]
UploadIdPath = Annotated[uuid.UUID, Path(description="prepare 返回的上传会话 id")]

# 只有浏览器能安全内联渲染的类型才保留原 Content-Type；HTML/SVG 文本等一律当附件下载。
_SAFE_INLINE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/x-icon",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
}


def _is_inline_safe(content_type: str | None) -> bool:
    return (content_type or "").lower() in _SAFE_INLINE_TYPES


def _content_headers(name: str, content_type: str, etag: str) -> dict[str, str]:
    encoded = quote(name, safe="")
    safe = _is_inline_safe(content_type)
    disposition = "inline" if safe else "attachment"
    return {
        "Content-Type": content_type if safe else "application/octet-stream",
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}",
        # 文件记录指向的字节不可变；按内容 hash 强缓存，历史会话里的图片无需重下
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": f'"{etag}"',
        # 直接打开接口地址时也不要让浏览器执行上传内容
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }


def _link_secret(settings: Settings) -> str:
    if not settings.secret_key:
        raise ConfigurationError("签发媒体直链需要配置 SECRET_KEY")
    return settings.secret_key


def _enforce_upload_limit(size: int, settings: Settings) -> None:
    """上限只在入口判一次；预检用浏览器报的 size，拿到字节后再按实际值复核。"""
    if size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // 1024 // 1024
        raise UnprocessableError(f"文件超过 {limit_mb} MB 上限")


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUserDep,
    file: Annotated[UploadFile, File()],
) -> FileRead:
    """小文件直传：服务端算 hash 入册（同样走秒传去重）。"""
    if file.size is not None:
        _enforce_upload_limit(file.size, settings)
    body = await file.read()
    if not body:
        raise UnprocessableError("空文件不保存")
    _enforce_upload_limit(len(body), settings)
    return await file_service.direct_upload(
        db, settings, storage, user.id, file.filename, file.content_type, body
    )


@router.post("/prepare", response_model=FilePrepareOut, status_code=status.HTTP_201_CREATED)
async def prepare_file(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUserDep,
    payload: FilePrepare,
) -> FilePrepareOut:
    """秒传探测：命中直接建引用；未命中返回 presign PUT 套餐。"""
    _enforce_upload_limit(payload.size, settings)
    return await file_service.instant_create(db, settings, storage, user.id, payload)


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
)
async def complete_upload(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUserDep,
    upload_id: UploadIdPath,
) -> FileRead:
    """PUT 完成后的登记：服务端复核指纹，搬运到内容寻址的正式 key。"""
    return await file_service.complete_upload(db, settings, storage, user.id, upload_id)


@router.get("", response_model=list[FileRead])
async def list_files(
    db: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[FileRead]:
    """我的文件（未软删的），新的在前。"""
    return await file_service.list_files(db, user.id, limit=limit)


@router.get("/{file_id}/link", response_model=FileLinkOut)
async def create_file_link(
    db: SessionDep,
    storage: StorageDep,
    user: CurrentUserDep,
    settings: SettingsDep,
    file_id: FileIdPath,
) -> FileLinkOut:
    """给页面里的 <img>/<video> 签一条短时效对象存储直链：字节不再过应用。"""
    file = await file_service.assert_readable(db, user.id, file_id)
    ttl = settings.file_link_ttl_seconds
    url = await file_service.presigned_for(
        db,
        storage,
        file,
        inline=_is_inline_safe(effective_media_type(file.name, file.content_type)),
        ttl_seconds=ttl,
    )
    return FileLinkOut(url=url, expires_at=datetime.now(UTC) + timedelta(seconds=ttl))


@router.get("/{file_id}/raw")
async def read_linked_file(
    db: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file_id: FileIdPath,
    exp: Annotated[int, Query(ge=0)],
    sig: Annotated[str, Query(min_length=16, max_length=128)],
) -> Response:
    """旧版同源直链：验签后 307 到对象存储，字节不再过应用。"""
    if not file_link.verify(_link_secret(settings), file_id, exp, sig):
        raise ForbiddenError("媒体链接无效或已过期")
    file = await file_service.readable(db, file_id)
    url = await file_service.presigned_for(
        db,
        storage,
        file,
        inline=_is_inline_safe(effective_media_type(file.name, file.content_type)),
        ttl_seconds=settings.file_link_ttl_seconds,
    )
    # 重定向本身不缓存：预签名地址过期后重新点旧链接仍能拿到新签名
    return RedirectResponse(
        url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{file_id}/content")
async def read_file_content(
    db: SessionDep,
    storage: StorageDep,
    user: CurrentUserDep,
    file_id: FileIdPath,
) -> Response:
    """同源回字节：页面里的 fetch 带 Bearer 取 blob。

    图片/视频优先走 /link 直连对象存储；这里保留给下载和直连失败时的兜底。
    """
    data, name, content_type, etag = await file_service.content_of(db, storage, user.id, file_id)
    return Response(content=data, headers=_content_headers(name, content_type, etag))


@router.get("/{file_id}")
async def download_file(
    db: SessionDep,
    storage: StorageDep,
    user: CurrentUserDep,
    file_id: FileIdPath,
) -> Response:
    # 307 到短时效签名地址：文件字节不过应用，原始文件名经 Content-Disposition 贴回
    url = await file_service.visit(db, storage, user.id, file_id)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    db: SessionDep,
    storage: StorageDep,
    user: CurrentUserDep,
    file_id: FileIdPath,
) -> Response:
    """软删引用；物理块归零引用后由 GC 收走。"""
    await file_service.soft_delete(db, user.id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
