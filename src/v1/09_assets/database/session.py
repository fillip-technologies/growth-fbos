from collections.abc import AsyncGenerator
import ssl

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config import settings


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def _build_connect_args() -> dict:
    if _is_sqlite():
        return {}
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


async def dispose_engine() -> None:
    await engine.dispose()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
