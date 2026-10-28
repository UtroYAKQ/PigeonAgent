"""文件端到端流：直传、秒传、presign 上传 + 复核、临时 URL、软删与 GC。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import app
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.models.upload_session import UploadSession
from app.services.blob_gc import sweep
from app.services.storage import PutResult, get_storage, upload_key
from tests.conftest import TEST_SECRET_KEY

BODY = b"pigeon payload"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeStorage:
    """内存桶：只实现 ObjectStorage 协议。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key: str, body: bytes, content_type: str | None) -> PutResult:
        self.objects[key] = body
        return PutResult(key=key, size=len(body))

    async def head(self, key: str) -> PutResult | None:
        if key not in self.objects:
            return None
        return PutResult(key=key, size=len(self.objects[key]))

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def copy(self, source: str, target: str) -> None:
        self.objects[target] = self.objects[source]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def url_for(self, key: str, *, download_name: str | None = None) -> str:
        return f"https://s3.test/{key}?name={download_name}"

    async def presign_put(self, key: str) -> str:
        return f"https://s3.test/{key}?put"


def storage_override(fake: FakeStorage) -> None:
    app.dependency_overrides[get_storage] = lambda: fake


async def _register(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "long-enough"}
    )
    body: dict[str, Any] = response.json()
    token: str = body["tokens"]["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _key_of_temp(upload_url: str) -> str:
    return upload_url.split("?", 1)[0].split(".test/", 1)[1]


def key_of_temp(upload_url: str) -> str:
    """https://s3.test/<key>?...) → <key>。"""
    head_with_scheme = upload_url.split("?", 1)[0]
    return head_with_scheme.split(".test/", 1)[1]


# ---------------------------------------------------------------- 直传

async def test_direct_upload_deduplicates_by_content(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)

    first = await client.post(
        "/api/v1/files", headers=headers, files={"file": ("a.png", BODY, "image/png")}
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["sha256"] == sha(BODY) and body["size"] == len(BODY)

    second = await client.post(
        "/api/v1/files", headers=headers, files={"file": ("b.png", BODY, "image/png")}
    )
    assert second.status_code == 201
    # 同内容只存一份物理对象，但逻辑文件多一行
    assert len([key for key in fake.objects if key.startswith("blobs/")]) == 1
    rows = (await db_session.scalars(select(FileRecord))).all()
    assert len(rows) == 2 and {row.name for row in rows} == {"a.png", "b.png"}


async def test_direct_upload_rejects_empty_and_oversize(client: AsyncClient) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    empty = await client.post(
        "/api/v1/files", headers=bearer(token), files={"file": ("a.txt", b"", None)}
    )
    assert empty.status_code == 422
    big = await client.post(
        "/api/v1/files", headers=bearer(token), files={"file": ("a.txt", "x" * 40_000_000, None)}
    )
    assert big.status_code == 422
    assert fake.objects == {}


# ---------------------------------------------------------------- 秒传 + presign

async def test_instant_upload_uses_no_transfer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)

    seed = await client.post(
        "/api/v1/files", headers=headers, files={"file": ("seed.txt", BODY, None)}
    )
    fingerprint = seed.json()["sha256"]
    # 把桶里的对象销毁：秒传的判定权在 blobs 表，而不是桶
    seed_key = next(key for key in fake.objects if key.startswith("blobs/"))
    fake.objects.pop(seed_key)

    prepare = await client.post(
        "/api/v1/files/prepare",
        headers=headers,
        json={"name": "换名字 也行.txt", "size": len(BODY), "sha256": fingerprint},
    )
    assert prepare.status_code == 201
    out = prepare.json()
    assert out["deduplicated"] is True
    assert out["file"]["sha256"] == fingerprint
    assert out["upload_id"] is None
    rows = (await db_session.scalars(select(FileRecord))).all()
    assert len(rows) == 2, "同内容第二行引用建起来了"
    assert fake.objects == {}, "0 字节传输：桶里不再落新对象"


async def test_presign_flow_completes_with_verification(client: AsyncClient) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)

    prepare = await client.post(
        "/api/v1/files/prepare",
        headers=headers,
        json={"name": "later.txt", "size": len(BODY), "sha256": sha(BODY)},
    )
    out = prepare.json()
    assert out["deduplicated"] is False
    assert out["upload_url"].startswith("https://s3.test/")
    upload_id = out["upload_id"]

    temp_key = key_of_temp(out["upload_url"])
    fake.objects[temp_key] = BODY
    done = await client.post(f"/api/v1/files/uploads/{upload_id}/complete", headers=headers)
    assert done.status_code == 201, done.text
    assert done.json()["size"] == len(BODY)
    assert any(key.startswith("blobs/") for key in fake.objects)
    assert temp_key in fake.deleted, "临时 key 用完就清"


async def test_presign_flow_rejects_hash_mismatch_and_size_lies(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)

    prepare = await client.post(
        "/api/v1/files/prepare",
        headers=headers,
        json={"name": "a.txt", "size": len(BODY) + 1, "sha256": sha(BODY)},
    )
    upload_id = prepare.json()["upload_id"]
    warm_key = key_of_temp(prepare.json()["upload_url"])
    fake.objects[warm_key] = BODY
    size_fail = await client.post(f"/api/v1/files/uploads/{upload_id}/complete", headers=headers)
    assert size_fail.status_code == 422
    assert "大小不符" in size_fail.json()["detail"]

    prepare = await client.post(
        "/api/v1/files/prepare",
        headers=headers,
        json={"name": "b.txt", "size": 3, "sha256": "f" * 64},
    )
    upload_id = prepare.json()["upload_id"]
    hot_key = key_of_temp(prepare.json()["upload_url"])
    fake.objects[hot_key] = b"abc"
    hash_fail = await client.post(f"/api/v1/files/uploads/{upload_id}/complete", headers=headers)
    assert hash_fail.status_code == 422
    assert hot_key in fake.deleted, "指纹对不上的对象直接丢弃"
    rows = (await db_session.scalars(select(FileRecord))).all()
    assert not [row for row in rows if row.blob_hash == "f" * 64]


# ---------------------------------------------------------------- 临时 URL 与归属

async def test_download_redirects_and_respects_ownership(client: AsyncClient) -> None:
    fake = FakeStorage()
    storage_override(fake)
    owner_token = await _register(client, "owner@example.com")
    file_id = (
        await client.post(
            "/api/v1/files", headers=bearer(owner_token), files={"file": ("报告.txt", BODY, None)}
        )
    ).json()["id"]

    mine = await client.get(
        f"/api/v1/files/{file_id}", headers=bearer(owner_token), follow_redirects=False
    )
    assert mine.status_code == 307
    assert mine.headers["location"].startswith("https://s3.test/blobs/")

    stranger_token = await _register(client, "stranger@example.com")
    stranger = await client.get(
        f"/api/v1/files/{file_id}", headers=bearer(stranger_token), follow_redirects=False
    )
    assert stranger.status_code == 404, "别人的文件 id 一律 404"

    missing = await client.get(
        "/api/v1/files/00000000-0000-0000-0000-000000000000",
        headers=bearer(owner_token),
        follow_redirects=False,
    )
    assert missing.status_code == 404


async def test_content_endpoint_serves_bytes_with_ownership(client: AsyncClient) -> None:
    """浏览器取文件走同源 /content：带鉴权回字节，别人的 id 依旧 404。"""
    fake = FakeStorage()
    storage_override(fake)
    owner_token = await _register(client, "content@example.com")
    file_id = (
        await client.post(
            "/api/v1/files",
            headers=bearer(owner_token),
            files={"file": ("图 1.png", BODY, "image/png")},
        )
    ).json()["id"]

    mine = await client.get(
        f"/api/v1/files/{file_id}/content", headers=bearer(owner_token)
    )
    assert mine.status_code == 200, mine.text
    assert mine.content == BODY
    assert mine.headers["content-type"] == "image/png"
    assert mine.headers["content-disposition"].startswith("inline;")

    stranger_token = await _register(client, "stranger-content@example.com")
    stranger = await client.get(
        f"/api/v1/files/{file_id}/content", headers=bearer(stranger_token)
    )
    assert stranger.status_code == 404, "别人的文件 id 一律 404"


async def test_delete_is_soft_and_blob_survives_other_refs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)
    first = (
        await client.post("/api/v1/files", headers=headers, files={"file": ("a.txt", BODY, None)})
    ).json()
    second = (
        await client.post("/api/v1/files", headers=headers, files={"file": ("b.txt", BODY, None)})
    ).json()

    deleted = await client.delete(f"/api/v1/files/{first['id']}", headers=headers)
    assert deleted.status_code == 204
    assert fake.deleted == [], "软删不碰物理对象"
    rows = (await db_session.scalars(select(FileRecord))).all()
    assert len([row for row in rows if row.deleted_at is not None]) == 1

    # 还有一行活引用，blob 不该被 GC
    gone = await client.get(f"/api/v1/files/{first['id']}", headers=headers, follow_redirects=False)
    assert gone.status_code == 404
    still = await client.get(
        f"/api/v1/files/{second['id']}", headers=headers, follow_redirects=False
    )
    assert still.status_code == 307


async def test_gc_purges_blob_only_after_refs_cleared(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    headers = bearer(token)
    uploaded = (
        await client.post("/api/v1/files", headers=headers, files={"file": ("a.txt", BODY, None)})
    ).json()

    # 有活引用：blob 绝不进删除候选
    await sweep(db_session, Settings(secret_key=TEST_SECRET_KEY, blob_grace_seconds=0), fake)
    assert len(fake.objects) == 1

    # 软删最后一个引用，宽限期 0 → 巡检直接收走
    await client.delete(f"/api/v1/files/{uploaded['id']}", headers=headers)
    await sweep(db_session, Settings(secret_key=TEST_SECRET_KEY, blob_grace_seconds=0), fake)
    assert len(fake.objects) == 0, "引用归零的物理块被回收"
    blobs_rows = (await db_session.scalars(select(Blob))).all()
    assert blobs_rows == []


async def test_gc_removes_expired_upload_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fake = FakeStorage()
    storage_override(fake)
    token = await _register(client, "up@example.com")
    prepare = await client.post(
        "/api/v1/files/prepare",
        headers=bearer(token),
        json={"name": "later.txt", "size": len(BODY), "sha256": sha(BODY)},
    )
    temp_key = key_of_temp(prepare.json()["upload_url"])
    fake.objects[temp_key] = BODY

    # 会话还没过期：GC 不动它
    sweep_settings = Settings(secret_key=TEST_SECRET_KEY)
    await sweep(db_session, sweep_settings, fake)
    assert temp_key in fake.objects

    # 手动把会话改过期再扫
    session_row = (await db_session.scalars(select(UploadSession))).first()
    assert session_row is not None
    session_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    await sweep(db_session, sweep_settings, fake)
    assert temp_key in fake.deleted
    assert (await db_session.scalars(select(UploadSession))).first() is None


def test_upload_key_shape() -> None:
    key = upload_key("pigeon")
    assert key.startswith("pigeon/tmp-uploads/")
    assert key != upload_key("pigeon"), "每个会话独占一个临时 key"
