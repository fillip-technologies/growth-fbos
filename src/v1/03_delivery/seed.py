"""
Seed script for the 03_delivery service: the built-in project and task types every
organization shares (services/builtins.py).

Run after the migrations (start.sh); safe to run any number of times.
"""

import asyncio
import os
import sys

# Ensure service directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.session import async_session_factory, dispose_engine
from services.builtins import ensure_builtin_types


async def seed_delivery() -> None:
    async with async_session_factory() as session:
        await ensure_builtin_types(session)
        await session.commit()
    await dispose_engine()
    print("🌱 [03_delivery] Built-in project and task types are in place")


if __name__ == "__main__":
    asyncio.run(seed_delivery())
