"""
Per-request timing, reported in a `Server-Timing` response header.

Every response says how many SQL statements it ran and how long they took, plus how the
auth cache answered, e.g. `db;dur=81.4;desc="1 queries", cache;desc="3 hit 0 miss", app;dur=96.0`.
Browsers show the header in the Network panel's Timing tab, so a slow endpoint can be
attributed to the database (a remote one costs ~80 ms per round trip) without a profiler.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import logging
import time
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass
class RequestUsage:
    queries: int = 0
    query_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0


logger = logging.getLogger("timing")

# Requests slower than this are logged with their query count, so slow endpoints show up in
# the service log without opening a browser.
SLOW_REQUEST_SECONDS = 0.5

_current_usage: ContextVar[Optional[RequestUsage]] = ContextVar("request_usage", default=None)


def current_usage() -> Optional[RequestUsage]:
    """The usage record of the request being handled, or None outside a request."""
    return _current_usage.get()


def track_queries(engine: Engine) -> None:
    """Count every statement `engine` executes against the current request."""

    @event.listens_for(engine, "before_cursor_execute")
    def _started(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        conn.info["query_started_at"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _finished(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        usage = _current_usage.get()
        started_at = conn.info.pop("query_started_at", None)
        if usage is None or started_at is None:
            return
        usage.queries += 1
        usage.query_seconds += time.perf_counter() - started_at


def _server_timing(usage: RequestUsage, total_seconds: float) -> str:
    parts = [f'db;dur={usage.query_seconds * 1000:.1f};desc="{usage.queries} queries"']
    if usage.cache_hits or usage.cache_misses:
        parts.append(f'cache;desc="{usage.cache_hits} hit {usage.cache_misses} miss"')
    parts.append(f"app;dur={total_seconds * 1000:.1f}")
    return ", ".join(parts)


class ServerTimingMiddleware:
    """Pure ASGI middleware: the usage record is shared with the endpoint's task."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        usage = RequestUsage()
        token = _current_usage.set(usage)
        started_at = time.perf_counter()

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed = time.perf_counter() - started_at
                timing = _server_timing(usage, elapsed)
                MutableHeaders(scope=message).append("Server-Timing", timing)
                if elapsed >= SLOW_REQUEST_SECONDS:
                    logger.warning("Slow request %s %s -> %s: %s", scope["method"], scope["path"], message["status"], timing)
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            _current_usage.reset(token)
