from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_database_and_propagates_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ready", headers={"X-Request-ID": "test-rid"})
    assert response.status_code == 200, response.text
    assert response.json()["database"] == "up"
    assert response.headers["x-request-id"] == "test-rid"
    assert response.headers["x-content-type-options"] == "nosniff"

    health = await client.get("/api/v1/health")
    assert health.headers["x-request-id"]
