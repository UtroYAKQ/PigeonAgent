"""应用配置项：入库、加密、公开读取，以及配置对业务能力的实际影响。"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.config_specs import CONFIG_SPECS
from app.core.security import decrypt_secret
from app.models.app_config import AppConfig
from app.services import app_config as config_service
from tests.conftest import TEST_SECRET_KEY


async def _get_item(client: AsyncClient, key: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.get("/api/v1/configs", **kwargs)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return next(item for item in items if item["key"] == key)


async def _stored(db_session: AsyncSession, key: str) -> AppConfig:
    row = await db_session.scalar(select(AppConfig).where(AppConfig.key == key))
    assert row is not None
    return row


async def test_configs_are_seeded_with_categories_and_secrets_masked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.get("/api/v1/configs")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(CONFIG_SPECS)

    items = {item["key"]: item for item in body["items"]}
    assert set(items) == {spec.key for spec in CONFIG_SPECS}
    assert {item["category"] for item in items.values()} == {
        "site",
        "deepseek",
        "sandbox",
        "email",
        "files",
        "logging",
        "features",
        "billing",
    }
    # 功能开关默认全开，升级不影响已有行为
    assert items["feature_web_search_enabled"]["value"] == "true"
    assert items["feature_image_generation_enabled"]["value"] == "true"
    assert items["feature_sandbox_enabled"]["value"] == "true"
    # 积分默认关：单价没配好之前不能把人挡在门外
    assert items["billing_enabled"]["value"] == "false"
    assert items["site_name"]["label"] == "站点名称"
    assert items["deepseek_api_key"]["is_secret"] is True
    assert items["deepseek_api_key"]["value"] is None
    assert items["operation_log_enabled"]["category"] == "logging"
    assert items["operation_log_retention_days"]["category"] == "logging"
    assert items["smtp_tls"]["value"] == "starttls"

    # 种子行确实落库了
    assert await _stored(db_session, "site_name")
    assert await _stored(db_session, "sandbox_template")


async def test_update_site_config_and_public_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    before = await client.get("/api/v1/configs/public")
    assert before.status_code == 200
    assert before.json()["site_name"] == "PigeonAgent"

    updated = await client.patch("/api/v1/configs/site_name", json={"value": "测试站点"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == "测试站点"
    assert updated.json()["source"] == "database"

    public = await client.get("/api/v1/configs/public")
    assert public.json()["site_name"] == "测试站点"

    # null = 撤销覆盖，回落到环境变量 / 代码默认
    cleared = await client.patch("/api/v1/configs/site_name", json={"value": None})
    assert cleared.status_code == 200
    assert cleared.json()["value"] == "PigeonAgent"
    assert cleared.json()["source"] == "default"
    assert (await _stored(db_session, "site_name")).value is None


async def test_numeric_config_accepts_json_numbers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """数字输入框交给前端的是 JSON number；只认字符串的话管理员填端口就 422。"""
    as_number = await client.patch("/api/v1/configs/smtp_port", json={"value": 587})
    assert as_number.status_code == 200, as_number.text
    assert as_number.json()["value"] == "587"

    as_text = await client.patch("/api/v1/configs/smtp_port", json={"value": "465"})
    assert as_text.status_code == 200, as_text.text
    assert as_text.json()["value"] == "465"

    bad = await client.patch("/api/v1/configs/smtp_port", json={"value": "abc"})
    assert bad.status_code == 422


async def test_boolean_config_accepts_words_and_flags(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """'false' 是非空字符串，按真假判断会被误存成 true。"""
    off = await client.patch("/api/v1/configs/operation_log_enabled", json={"value": "false"})
    assert off.status_code == 200, off.text
    assert off.json()["value"] == "false"

    on = await client.patch("/api/v1/configs/operation_log_enabled", json={"value": True})
    assert on.status_code == 200, on.text
    assert on.json()["value"] == "true"


async def test_secret_is_encrypted_masked_and_drives_web_search(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    caps = await client.get("/api/v1/capabilities")
    assert caps.json()["web_search"] is False
    updated = await client.patch(
        "/api/v1/configs/deepseek_api_key", json={"value": "sk-test-deepseek"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_secret"] is True
    assert updated.json()["value"] is None
    assert updated.json()["has_value"] is True

    row = await _stored(db_session, "deepseek_api_key")
    assert row.value is not None
    assert row.value != "sk-test-deepseek"
    assert decrypt_secret(row.value, TEST_SECRET_KEY) == "sk-test-deepseek"

    caps = await client.get("/api/v1/capabilities")
    assert caps.json()["web_search"] is True

    # 列表接口只给掩码，不回显明文
    item = await _get_item(client, "deepseek_api_key")
    assert item["value"] is None
    assert item["has_value"] is True

    cleared = await client.patch("/api/v1/configs/deepseek_api_key", json={"value": None})
    assert cleared.status_code == 200
    assert cleared.json()["has_value"] is False
    assert (await client.get("/api/v1/capabilities")).json()["web_search"] is False


async def test_sandbox_has_a_platform_feature_switch(client: AsyncClient) -> None:
    item = await _get_item(client, "feature_sandbox_enabled")
    assert item["label"] == "允许沙箱执行"

    updated = await client.patch("/api/v1/configs/feature_sandbox_enabled", json={"value": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == "false"


async def test_invalid_config_values_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    cases = [
        ("smtp_tls", "bogus"),
        ("smtp_port", "not-a-port"),
        ("sandbox_idle_seconds", "30"),
        ("max_upload_bytes", "10"),
    ]
    for key, value in cases:
        response = await client.patch(f"/api/v1/configs/{key}", json={"value": value})
        assert response.status_code == 422, (key, response.text)

    missing = await client.patch("/api/v1/configs/not_a_real_key", json={"value": "x"})
    assert missing.status_code == 404

    # 失败不落库
    row = await _stored(db_session, "smtp_tls")
    assert row.value is None


async def test_missing_config_values_are_imported_on_each_start(
    db_session: AsyncSession,
) -> None:
    empty = Settings(_env_file=None, secret_key=TEST_SECRET_KEY)
    base = Settings(_env_file=None, secret_key=TEST_SECRET_KEY, site_name="来自环境变量")

    # 先在没有环境变量时建行，值为 NULL
    await config_service.seed_defaults(db_session, empty)
    assert (await _stored(db_session, "site_name")).value is None

    # 下次启动环境变量有了值，自动补进数据库
    await config_service.seed_defaults(db_session, base)
    assert (await _stored(db_session, "site_name")).value == "来自环境变量"

    # 管理员撤销覆盖后，再下一次启动会重新从环境变量补入
    await config_service.update_item(db_session, "site_name", None, base)
    await config_service.seed_defaults(db_session, base)
    assert (await _stored(db_session, "site_name")).value == "来自环境变量"


async def test_precedence_database_over_environment_over_code_default(
    db_session: AsyncSession,
) -> None:
    base = Settings(
        secret_key=TEST_SECRET_KEY,
        site_name="来自环境变量",
        deepseek_api_key="env-deepseek-key",
    )
    await config_service.seed_defaults(db_session, base)

    # 首次启动把环境变量值导入数据库；代码默认值不落库
    assert (await _stored(db_session, "site_name")).value == "来自环境变量"
    assert (await _stored(db_session, "deepseek_api_key")).value is not None
    assert (await _stored(db_session, "site_description")).value is None

    items = {item.key: item for item in await config_service.list_items(db_session, base)}
    assert items["site_name"].source == "database"
    assert items["site_name"].value == "来自环境变量"
    assert items["deepseek_api_key"].source == "database"
    assert items["deepseek_api_key"].has_value is True
    assert items["site_description"].source == "default"

    # 数据库导入后就是唯一来源，再次保存相同值也保留数据库覆盖
    same = await config_service.update_item(db_session, "site_name", "来自环境变量", base)
    assert same.source == "database"
    assert (await _stored(db_session, "site_name")).value == "来自环境变量"

    # 数据库设置不同值后仍以数据库为准
    overridden = await config_service.update_item(db_session, "site_name", "来自数据库", base)
    assert overridden.source == "database"
    resolved = await config_service.resolve_settings(db_session, base)
    assert resolved.site_name == "来自数据库"

    # 撤销覆盖后回到环境变量；下次启动会重新补入数据库
    cleared = await config_service.update_item(db_session, "site_name", None, base)
    assert cleared.source == "environment"
    assert (await config_service.resolve_settings(db_session, base)).site_name == "来自环境变量"
    await config_service.seed_defaults(db_session, base)
    assert (await _stored(db_session, "site_name")).value == "来自环境变量"


async def test_only_admin_can_manage_configs(client: AsyncClient) -> None:
    member = await client.post(
        "/api/v1/auth/register",
        json={"email": "member-config@example.com", "password": "long-enough"},
    )
    assert member.status_code == 201, member.text
    headers = {"Authorization": f"Bearer {member.json()['tokens']['access_token']}"}

    listing = await client.get("/api/v1/configs", headers=headers)
    assert listing.status_code == 403
    update = await client.patch(
        "/api/v1/configs/site_name", headers=headers, json={"value": "成员改的"}
    )
    assert update.status_code == 403

    # 公开站点信息不需要登录
    public = await client.get("/api/v1/configs/public", headers={"Authorization": ""})
    assert public.status_code == 200


async def test_email_config_from_database_drives_registration(
    client: AsyncClient, monkeypatch: Any
) -> None:
    sent: list[tuple[str, str]] = []

    async def fake_send_mail(settings: Any, to_email: str, subject: str, body: str) -> bool:
        sent.append((to_email, body))
        return True

    monkeypatch.setattr("app.services.user.mailer.send_mail", fake_send_mail)

    for key, value in [
        ("smtp_host", "smtp.example.com"),
        ("smtp_port", "2525"),
        ("smtp_tls", "none"),
        ("email_verification_required", "true"),
    ]:
        response = await client.patch(f"/api/v1/configs/{key}", json={"value": value})
        assert response.status_code == 200, response.text

    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "verify-from-db@example.com", "password": "long-enough"},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["verification_required"] is True
    assert registered.json()["tokens"] is None
    assert len(sent) == 1
    assert sent[0][0] == "verify-from-db@example.com"
