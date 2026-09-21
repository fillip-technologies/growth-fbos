import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# alembic.ini's prepend_sys_path = . adds the service root to sys.path,
# so all service-level absolute imports work here identically to the running app.
from database.base import Base
import models  # noqa: F401 — executes models/__init__.py, registering all ORM classes with Base.metadata

alembic_cfg = context.config
fileConfig(alembic_cfg.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    from config import settings
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_on_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_get_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations_on_connection)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
