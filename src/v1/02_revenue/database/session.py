import asyncio
from collections.abc import AsyncGenerator
import logging
import ssl
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import configure_mappers

from config import settings
from utils.timing import track_queries

logger = logging.getLogger(__name__)


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def _build_connect_args() -> dict:
    if _is_sqlite():
        return {}
    # Outlive the server's short default idle timeout (see config.db_session_wait_timeout).
    connect_args: dict = {"init_command": f"SET SESSION wait_timeout={settings.db_session_wait_timeout}"}
    if settings.db_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx
    return connect_args


def _build_engine() -> AsyncEngine:
    kwargs = {
        "echo": settings.debug,
        "connect_args": _build_connect_args(),
    }
    if not _is_sqlite():
        kwargs.update({
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_pre_ping": settings.db_pool_pre_ping,
            "pool_recycle": settings.db_pool_recycle,
        })
    return create_async_engine(settings.database_url, **kwargs)


engine = _build_engine()
track_queries(engine.sync_engine)

_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
async_session_factory = _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session


async def _open_pooled_connection() -> Optional[Exception]:
    """Open one connection and return it to the pool; the error if the database refused."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (DBAPIError, OSError) as error:
        return error
    return None


async def warm_pool() -> None:
    """
    Prepare at startup what the first requests after a deploy would otherwise pay for: the
    ORM's mapper setup, and the pool's connections (about a second each against the remote
    database). A connection failure only costs that time later, so it is logged rather
    than stopping the service.
    """
    # Mapper setup otherwise runs inside the first request (and blocks every other one).
    configure_mappers()
    if _is_sqlite():
        return
    results = await asyncio.gather(*(_open_pooled_connection() for _ in range(settings.db_pool_size)))
    errors = [error for error in results if error is not None]
    if errors:
        logger.warning("Could not pre-open %d of %d database connections: %s", len(errors), len(results), errors[0])


async def dispose_engine() -> None:
    await engine.dispose()
