"""The Alembic migrations build exactly the tables the models describe (start.sh runs them in production)."""
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from sqlalchemy import create_engine

from database.base import Base
import models  # noqa: F401

SERVICE_ROOT = Path(__file__).resolve().parent.parent


def test_single_head():
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_migrations_match_models(tmp_path):
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    engine = create_engine(f"sqlite:///{tmp_path / 'finance.db'}")

    with engine.begin() as connection:
        def upgrade(rev, context):
            return script._upgrade_revs("head", rev)

        with EnvironmentContext(config, script, fn=upgrade, destination_rev="head") as env:
            env.configure(connection=connection, target_metadata=Base.metadata)
            with env.begin_transaction():
                env.run_migrations()

        context = MigrationContext.configure(connection, opts={"compare_type": False})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []
