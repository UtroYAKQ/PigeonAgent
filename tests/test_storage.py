"""对象存储层：不连真桶，假 client 覆盖行为。"""

import io
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.exceptions import StorageError, StorageUnavailableError
from app.services.storage import PutResult, S3Storage, safe_name
from tests.conftest import TEST_SECRET_KEY


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "secret_key": TEST_SECRET_KEY,
        "s3_bucket": "pigeon-files",
        "s3_access_key": "ak",
        "s3_secret_key": "sk",
    }
    base.update(overrides)
    return Settings(**base)


class FakeClient:
    """只实现 S3Storage 用到的方法，参数名和 botocore 保持一致。"""

    def __init__(self, fail_put: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_put = fail_put
        self.bodies: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(("put_object", kwargs))
        if self.fail_put:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
        self.bodies[kwargs["Key"]] = kwargs["Body"]

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_object", kwargs))
        if kwargs["Key"] not in self.bodies:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.bodies[kwargs["Key"]])}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        if kwargs["Key"] not in self.bodies:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.bodies[kwargs["Key"]])}

    def copy_object(self, **kwargs: Any) -> None:
        self.calls.append(("copy_object", kwargs))
        source = kwargs["CopySource"]["Key"]
        self.bodies[kwargs["Key"]] = self.bodies[source]

    def delete_object(self, **kwargs: Any) -> None:
        self.calls.append(("delete_object", kwargs))
        self.bodies.pop(kwargs["Key"], None)

    def generate_presigned_url(self, method: str, **kwargs: Any) -> str:
        self.calls.append(("generate_presigned_url", {"method": method, **kwargs}))
        params = kwargs["Params"]
        return f"https://s3.test/{params['Key']}?expires={kwargs['ExpiresIn']}"


def subject(**overrides: Any) -> S3Storage:
    return S3Storage(settings(**overrides), client=FakeClient())  # type: ignore[arg-type]


# ------------------------------------------------------------------ 名字与 key


def test_safe_name_drops_directories_and_odd_chars() -> None:
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name(r"C:\temp\月度 报告.PDF") == "月度_报告.PDF"
    assert safe_name("...") == "file"
    assert safe_name(None) == "file"


def test_upload_key_is_prefixed_and_not_enumerable() -> None:
    from app.services.storage import upload_key

    first, second = upload_key("pigeon"), upload_key("pigeon")
    assert first.startswith("pigeon/tmp-uploads/") and second.startswith("pigeon/tmp-uploads/")
    assert first != second, "两个会话不能共享同一个临时 key"


# ------------------------------------------------------------------ 存储层


async def test_put_reports_key_and_size() -> None:
    client = FakeClient()
    storage = S3Storage(settings(), client=client)  # type: ignore[arg-type]
    result = await storage.put("blobs/x", b"hello", "text/plain")
    assert (result.key, result.size) == ("blobs/x", 5)
    name, kwargs = client.calls[0]
    assert name == "put_object" and kwargs["ContentType"] == "text/plain"


async def test_head_tells_size_and_misses_tell_none() -> None:
    client = FakeClient()
    storage = S3Storage(settings(), client=client)  # type: ignore[arg-type]
    assert await storage.head("blobs/missing") is None
    await storage.put("blobs/x", b"abc", None)
    seen = await storage.head("blobs/x")
    assert seen is not None and seen.size == 3


async def test_get_round_trips_bytes() -> None:
    storage = S3Storage(settings(), client=FakeClient())  # type: ignore[arg-type]
    await storage.put("blobs/x", b"payload", None)
    assert await storage.get("blobs/x") == b"payload"


async def test_copy_moves_content_under_new_key() -> None:
    client = FakeClient()
    storage = S3Storage(settings(), client=client)  # type: ignore[arg-type]
    await storage.put("tmp/a", b"same content", None)
    await storage.copy("tmp/a", "blobs/b")
    assert await storage.get("blobs/b") == b"same content"
    copies = [call for call in client.calls if call[0] == "copy_object"]
    assert copies[0][1]["CopySource"]["Key"] == "tmp/a"


async def test_url_for_is_short_lived_signed_get_with_rfc5987_name() -> None:
    client = FakeClient()
    storage = S3Storage(settings(), client=client)  # type: ignore[arg-type]
    url = await storage.url_for("blobs/x", download_name="月度 报告.txt")
    assert url.startswith("https://s3.test/blobs/x")
    params = client.calls[-1][1]["Params"]
    assert params["ResponseContentDisposition"].startswith("attachment; filename=")
    assert "filename*=UTF-8''" in params["ResponseContentDisposition"]


async def test_presign_put_is_a_put_signature() -> None:
    client = FakeClient()
    await S3Storage(settings(), client=client).presign_put("tmp/a")  # type: ignore[arg-type]
    name, kwargs = client.calls[-1]
    assert name == "generate_presigned_url"
    assert kwargs["method"] == "put_object"


async def test_upstream_error_becomes_storage_error() -> None:
    storage = S3Storage(settings(), client=FakeClient(fail_put=True))  # type: ignore[arg-type]
    with pytest.raises(StorageError) as caught:
        await storage.put("k", b"x", None)
    assert caught.value.status_code == 502
    assert "AccessDenied" in str(caught.value)


async def test_delete_calls_upstream() -> None:
    client = FakeClient()
    await S3Storage(settings(), client=client).delete("blobs/x")  # type: ignore[arg-type]
    assert client.calls[0][0] == "delete_object"


def test_missing_bucket_reports_service_unavailable() -> None:
    with pytest.raises(StorageUnavailableError):
        S3Storage(settings(s3_bucket=None))


def test_put_result_shape() -> None:
    assert PutResult(key="k", size=1).key == "k"
