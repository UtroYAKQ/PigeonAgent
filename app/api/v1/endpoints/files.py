import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Path, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from app.api.deps import OptionalUserDep, SessionDep, SettingsDep
from app.core.exceptions import UnprocessableError
from app.schemas.file import FilePrepare, FilePrepareOut, FileRead
from app.services import file_service
from app.services.storage import ObjectStorage, get_storage

router = APIRouter(prefix="/files", tags=["files"])

StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
FileIdPath = Annotated[uuid.UUID, Path(description="逻辑文件 id")]
UploadIdPath = Annotated[uuid.UUID, Path(description="prepare 返回的上传会话 id")]


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUserDep,
    file: Annotated[UploadFile, File()],
) -> FileRead:
    """小文件直传：服务端算 hash 入册（同样走秒传去重）。"""
    body = await file.read()
    if not body:
        raise UnprocessableError("空文件不保存")
    if len(body) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // 1024 // 1024
        raise UnprocessableError(f"文件超过 {limit_mb} MB 上限")
    return await file_service.direct_upload(
        db, settings, storage, user.id if user else None, file.filename, file.content_type, body
    )


@router.post("/prepare", response_model=FilePrepareOut, status_code=status.HTTP_201_CREATED)
async def prepare_file(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUserDep,
    payload: FilePrepare,
) -> FilePrepareOut:
    """秒传探测：命中直接建引用；未命中返回 presign PUT 套餐。"""
    if payload.size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // 1024 // 1024
        raise UnprocessableError(f"文件超过 {limit_mb} MB 上限")
    return await file_service.instant_create(
        db, settings, storage, user.id if user else None, payload
    )


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
)
async def complete_upload(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUserDep,
    upload_id: UploadIdPath,
) -> FileRead:
    """PUT 完成后的登记：服务端复核指纹，搬运到内容寻址的正式 key。"""
    return await file_service.complete_upload(
        db, settings, storage, user.id if user else None, upload_id
    )


@router.get("", response_model=list[FileRead])
async def list_files(
    db: SessionDep,
    user: OptionalUserDep,
    limit: int = 100,
) -> list[FileRead]:
    """我的文件（未软删的），新的在前。"""
    return await file_service.list_files(db, user.id if user else None, limit=limit)


@router.get("/{file_id}/content")
async def read_file_content(
    db: SessionDep,
    storage: StorageDep,
    user: OptionalUserDep,
    file_id: FileIdPath,
) -> Response:
    """同源回字节：页面里的 fetch 带 Bearer 取 blob（图片渲染和资源下载都走这里）。

    307 直链留给外部系统；浏览器跨域跟随后会被桶的 CORS 策略挡掉。
    """
    data, name, content_type = await file_service.content_of(
        db, storage, user.id if user else None, file_id
    )
    encoded = quote(name, safe="")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded}",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/{file_id}")
async def download_file(
    db: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUserDep,
    file_id: FileIdPath,
) -> Response:
    # 307 到短时效签名地址：文件字节不过应用，原始文件名经 Content-Disposition 贴回
    url = await file_service.visit(db, storage, user.id if user else None, file_id)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    db: SessionDep,
    storage: StorageDep,
    user: OptionalUserDep,
    file_id: FileIdPath,
) -> Response:
    """软删引用；物理块归零引用后由 GC 收走。"""
    await file_service.soft_delete(db, user.id if user else None, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

