"""A dropped database connection answers a retryable 503, not a bare 500."""

from database.session import get_db_session
from main import app
import pytest
from sqlalchemy.exc import OperationalError


class DroppedConnectionSession:
    """A session whose connection the database has closed (e.g. after its idle timeout)."""

    async def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("(2013, 'Lost connection to MySQL server during query')"))


@pytest.mark.asyncio
async def test_lost_database_connection_is_a_retryable_503(async_client):
    async def dropped():
        yield DroppedConnectionSession()

    app.dependency_overrides[get_db_session] = dropped

    res = await async_client.get("/api/documents/v1/documents?limit=10")

    assert res.status_code == 503
    body = res.json()
    assert body["code"] == "DATABASE_UNAVAILABLE"
    assert body["retryable"] is True
