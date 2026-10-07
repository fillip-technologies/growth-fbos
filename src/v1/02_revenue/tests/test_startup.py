import pytest

from main import app, lifespan


# The other tests talk to the app without running its lifespan, so a broken startup (a client
# wired to a name that does not exist) would pass them all and only fail on the server.
@pytest.mark.asyncio
async def test_the_app_starts_and_stops():
    async with lifespan(app):
        assert app.state.identity_client is not None
        assert app.state.documents_client is not None
