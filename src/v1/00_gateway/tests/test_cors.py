"""CORS: answered only when CORS_ENABLED is on, for the origins CORS_ORIGINS lists."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main import configure_cors

PREFLIGHT = {"Origin": "http://localhost:5174", "Access-Control-Request-Method": "POST"}


def make_client(enabled: bool, origins: str = "*") -> TestClient:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    configure_cors(app, enabled, origins)
    return TestClient(app)


def test_off_sends_no_cors_headers() -> None:
    response = make_client(enabled=False).get("/ping", headers={"Origin": "http://localhost:5174"})

    assert "access-control-allow-origin" not in response.headers


def test_on_with_star_allows_any_origin() -> None:
    client = make_client(enabled=True)

    preflight = client.options("/ping", headers=PREFLIGHT)
    simple = client.get("/ping", headers={"Origin": "http://203.0.113.9:3000"})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert simple.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in simple.headers


def test_on_with_a_list_allows_only_those_origins() -> None:
    client = make_client(enabled=True, origins=" http://localhost:5174 , https://app.example.com")

    allowed = client.get("/ping", headers={"Origin": "http://localhost:5174"})
    other = client.get("/ping", headers={"Origin": "http://evil.example.com"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5174"
    assert "access-control-allow-origin" not in other.headers


def test_on_with_empty_origins_falls_back_to_star() -> None:
    response = make_client(enabled=True, origins="  ").get("/ping", headers={"Origin": "http://x.test"})

    assert response.headers["access-control-allow-origin"] == "*"
