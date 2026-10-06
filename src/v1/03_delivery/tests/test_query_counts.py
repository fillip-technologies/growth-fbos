"""
List pages load what their rows refer to once per page, not once per row: against the remote
database every extra query costs ~80 ms. The Server-Timing header counts a request's queries.
"""
import re
import uuid

from sqlalchemy.dialects import mysql
import pytest

from database.insert_ignore import insert_ignore
from models.code_sequence import CodeSequence
from tests.test_smoke import BASE, create_project, create_task

pytestmark = pytest.mark.asyncio


async def query_count(client, path: str) -> int:
    res = await client.get(f"{BASE}{path}")
    assert res.status_code == 200, res.text
    return int(re.search(r'desc="(\d+) queries"', res.headers["Server-Timing"]).group(1))


async def test_task_list_costs_the_same_for_one_row_or_ten(async_client):
    await create_task(async_client, checklist=[{"text": "Check"}])
    one_row = await query_count(async_client, "/tasks")
    assert one_row >= 3  # the page, its task types, its checklists: really counted
    for _ in range(9):
        await create_task(async_client, checklist=[{"text": "Check"}, {"text": "Check again"}])
    assert await query_count(async_client, "/tasks") == one_row


async def test_project_list_costs_the_same_for_one_row_or_ten(async_client):
    await create_project(async_client)
    one_row = await query_count(async_client, "/work-units")
    assert one_row >= 3
    for _ in range(9):
        await create_project(async_client, owning_unit_id=str(uuid.uuid4()))
    assert await query_count(async_client, "/work-units") == one_row


def test_counter_rows_are_created_with_insert_ignore_on_mysql():
    statement = insert_ignore(CodeSequence).values(organization_id=uuid.uuid4(), scope="WU-2026")
    assert str(statement.compile(dialect=mysql.dialect())).startswith("INSERT IGNORE INTO code_sequences")
