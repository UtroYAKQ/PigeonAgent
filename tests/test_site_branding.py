"""站点品牌：Logo 上传、公开读取与清除。"""

from __future__ import annotations

import base64

from httpx import AsyncClient

from tests.test_files import FakeStorage, storage_override

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl9sAAAAASUVORK5CYII="
)


async def test_site_logo_upload_read_and_delete(client: AsyncClient) -> None:
    fake = FakeStorage()
    storage_override(fake)

    uploaded = await client.post(
        "/api/v1/site/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    logo_url = uploaded.json()["site_logo_url"]
    assert "/configs/public/logo?v=" in logo_url
    assert fake.objects

    public_config = await client.get("/api/v1/configs/public")
    assert public_config.status_code == 200
    assert public_config.json()["site_logo_url"] == logo_url

    logo = await client.get("/api/v1/configs/public/logo")
    assert logo.status_code == 200
    assert logo.content == PNG_BYTES
    assert logo.headers["content-type"].startswith("image/png")

    deleted = await client.delete("/api/v1/site/logo")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/configs/public")).json()["site_logo_url"] is None
    assert (await client.get("/api/v1/configs/public/logo")).status_code == 404
