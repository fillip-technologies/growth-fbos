import pytest
import httpx


@pytest.mark.asyncio
async def test_health_check(async_client: httpx.AsyncClient):
    res = await async_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "people"
