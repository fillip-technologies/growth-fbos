"""
Kanban boards over tasks: one per project, and one per customer across all its projects.

A column holds one or more task statuses. Moving a card between two columns that both hold its
status only changes where it sits on the board. Moving it to a column with another status takes
the task's real step (start, take and start, unblock) under the same rules as the task's own
actions; a step that asks for more first (submit, block, review) is answered with
BOARD_MOVE_NEEDS_INPUT, and the console takes it through its dialog before placing the card.

Where a card shows is worked out when the board is read, so nothing has to be kept in sync: in
its saved column while that column holds the task's status, otherwise in the column marked
default for the status (else the first column, by position, that holds it).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, case, delete, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    BoardColumnNotFoundError,
    BoardMoveNeedsInputError,
    BoardMoveNotAllowedError,
    BoardNotFoundError,
    ColumnTakesNoNewTasksError,
    LastBoardColumnError,
    PermissionDeniedError,
    TaskNotFoundError,
    ValidationFailedError,
    WorkUnitNotFoundError,
)
from models.board import Board, BoardColumn, BoardItem
from models.task import Task
from models.work_unit import WorkUnit
from schemas.boards import (
    BoardColumnCreate,
    BoardColumnOrder,
    BoardColumnResponse,
    BoardColumnUpdate,
    BoardColumnView,
    BoardDetailResponse,
    BoardItemCreate,
    BoardItemPlace,
    BoardItemResponse,
    BoardSummary,
    BoardUpdate,
)
from services.assignees import PeopleDirectory
from services.identity_client import Actor
from services.ranks import MAX_RANK_LENGTH, rank_between, spread_ranks
import services.tasks as tasks
from services.tasks import TaskFilters
from services.versions import check_if_match
from services.views import project_view, task_view
from services.work_units import ensure_work_unit_visible

# What a project's or customer's board starts with (GitHub Projects' columns).
DEFAULT_COLUMNS: list[tuple[str, str, list[str]]] = [
    ("Backlog", "This item hasn't been started", ["draft", "open"]),
    ("Ready", "This is ready to be picked up", ["open", "assigned", "rework"]),
    ("In progress", "This is actively being worked on", ["in_progress", "blocked"]),
    ("In review", "This item is in review", ["submitted", "in_review"]),
    ("Done", "This has been completed", ["done"]),
]
DEFAULT_BOARD_NAME = "Board"
# Statuses a board is expected to show; cancelled work is left off unless a column asks for it.
_SHOWN_STATUSES = ["draft", "open", "assigned", "in_progress", "blocked", "submitted", "in_review", "rework", "done"]
# A new task starts in one of these (services/tasks.py `_insert_task`).
_NEW_TASK_STATUSES = {"draft", "open", "assigned"}
# Steps a move can't take without more from the person: the console asks first.
_STEPS_NEEDING_INPUT = {"submit", "block", "approve", "send_back"}


@dataclass(frozen=True)
class _Layout:
    """A board's columns in order, and which column each status falls back to."""

    columns: list[BoardColumn]
    homes: dict[str, uuid.UUID]

    @classmethod
    def of(cls, columns: list[BoardColumn]) -> "_Layout":
        homes: dict[str, uuid.UUID] = {}
        for column in sorted(columns, key=lambda c: (not c.is_default_for_status, c.seq)):
            for status in column.statuses or []:
                homes.setdefault(status, column.id)
        return cls(columns=columns, homes=homes)

    def column(self, column_id: uuid.UUID) -> BoardColumn:
        found = next((c for c in self.columns if c.id == column_id), None)
        if found is None:
            raise BoardColumnNotFoundError(str(column_id))
        return found

    def home_statuses(self, column: BoardColumn) -> list[str]:
        return [status for status, home in self.homes.items() if home == column.id]

    def uncovered(self) -> list[str]:
        return [status for status in _SHOWN_STATUSES if status not in self.homes]


# --- Which tasks a board shows, and in which column ---------------------------------


def _board_tasks(board: Board):
    """The tasks a board is about: its project's, or those of every project of its customer."""
    if board.work_unit_id is not None:
        return Task.work_unit_id == board.work_unit_id
    projects = select(WorkUnit.id).where(WorkUnit.organization_id == board.organization_id, WorkUnit.client_id == board.client_id)
    return Task.work_unit_id.in_(projects)


def _with_items(query, board: Board):
    return query.outerjoin(BoardItem, and_(BoardItem.task_id == Task.id, BoardItem.board_id == board.id))


def _in_column(layout: _Layout, column: BoardColumn):
    """In the saved column while it holds the task's status; otherwise in the status's home column."""
    saved_here = and_(BoardItem.column_id == column.id, Task.status.in_(column.statuses or []))
    placements = [and_(BoardItem.column_id == c.id, Task.status.in_(c.statuses or [])) for c in layout.columns]
    not_placed = or_(BoardItem.column_id.is_(None), not_(or_(*placements)))
    falls_back_here = and_(not_placed, Task.status.in_(layout.home_statuses(column)))
    return or_(saved_here, falls_back_here)


def _rank_in(column: BoardColumn):
    """The card's saved rank, if it was placed in this column (a card that fell back here has none)."""
    return case((BoardItem.column_id == column.id, BoardItem.rank), else_=None)


def _card_order(column: BoardColumn) -> tuple:
    """Cards placed by hand first, in their order, then the rest most urgent first."""
    rank = _rank_in(column)
    return (rank.is_(None).asc(), rank.asc(), *tasks._work_order())


# --- Loading and permissions -----------------------------------------------------------


async def _get_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID) -> Board:
    """The board, if it is in the caller's organization and they may see what it is about."""
    board = await session.scalar(select(Board).where(Board.id == board_id, Board.organization_id == actor.organization_id))
    if board is None:
        raise BoardNotFoundError(str(board_id))
    if board.work_unit_id is not None:
        try:
            await _ensure_project_in_view(session, actor, board.work_unit_id)
        except WorkUnitNotFoundError:
            raise BoardNotFoundError(str(board_id)) from None
    return board


async def _ensure_project_in_view(session: AsyncSession, actor: Actor, work_unit_id: uuid.UUID) -> WorkUnit:
    project = await session.scalar(
        select(WorkUnit).where(WorkUnit.id == work_unit_id, WorkUnit.organization_id == actor.organization_id)
    )
    if project is None:
        raise WorkUnitNotFoundError(str(work_unit_id))
    view = await project_view(session, actor)
    if view is not None:
        await ensure_work_unit_visible(session, actor.organization_id, work_unit_id, view)
    return project


async def _layout(session: AsyncSession, board_id: uuid.UUID) -> _Layout:
    rows = await session.scalars(select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.seq))
    return _Layout.of(list(rows.all()))


async def _may_configure(session: AsyncSession, actor: Actor, board: Board) -> bool:
    """Task managers set up any board; a project's manager sets up their project's."""
    if actor.has(permissions.TASK_WRITE):
        return True
    if board.work_unit_id is None:
        return False
    manager = await session.scalar(select(WorkUnit.manager_user_id).where(WorkUnit.id == board.work_unit_id))
    return manager is not None and manager == actor.user_id


async def _configurable_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID) -> Board:
    board = await _get_board(session, actor, board_id)
    if not await _may_configure(session, actor, board):
        raise PermissionDeniedError(permissions.TASK_WRITE)
    return board


def _touch(board: Board) -> None:
    board.version += 1
    board.updated_at = datetime.now(timezone.utc)


def _summary(board: Board) -> BoardSummary:
    return BoardSummary(
        id=board.id,
        name=board.name,
        work_unit_id=board.work_unit_id,
        client_id=board.client_id,
        is_default=board.is_default,
        version=board.version,
    )


def _column_response(column: BoardColumn) -> BoardColumnResponse:
    return BoardColumnResponse(
        id=column.id,
        seq=column.seq,
        name=column.name,
        description=column.description,
        color=column.color,
        statuses=list(column.statuses or []),
        wip_limit=column.wip_limit,
        is_default_for_status=column.is_default_for_status,
    )


# --- Boards ---------------------------------------------------------------------------


async def list_boards(
    session: AsyncSession, actor: Actor, work_unit_id: Optional[uuid.UUID], client_id: Optional[uuid.UUID]
) -> list[BoardSummary]:
    """A project's or a customer's boards; the default one is made the first time it's asked for."""
    if (work_unit_id is None) == (client_id is None):
        raise ValidationFailedError("work_unit_id", "Give either a project (work_unit_id) or a customer (client_id)")
    owning_unit_id = None
    if work_unit_id is not None:
        project = await _ensure_project_in_view(session, actor, work_unit_id)
        owning_unit_id = project.owning_unit_id
        scope = Board.work_unit_id == work_unit_id
    else:
        scope = and_(Board.client_id == client_id, Board.work_unit_id.is_(None))
    query = select(Board).where(Board.organization_id == actor.organization_id, scope).order_by(
        Board.is_default.desc(), Board.created_at, Board.id
    )
    boards = list((await session.scalars(query)).all())
    if not boards:
        boards = [await _create_default_board(session, actor, work_unit_id, client_id, owning_unit_id)]
    return [_summary(board) for board in boards]


async def _create_default_board(
    session: AsyncSession,
    actor: Actor,
    work_unit_id: Optional[uuid.UUID],
    client_id: Optional[uuid.UUID],
    owning_unit_id: Optional[uuid.UUID],
) -> Board:
    board = Board(
        organization_id=actor.organization_id,
        work_unit_id=work_unit_id,
        client_id=client_id,
        owning_unit_id=owning_unit_id,
        name=DEFAULT_BOARD_NAME,
        is_default=True,
        created_by=actor.user_id,
        version=1,
    )
    session.add(board)
    await session.flush()
    for seq, (name, description, statuses) in enumerate(DEFAULT_COLUMNS, start=1):
        session.add(
            BoardColumn(board_id=board.id, seq=seq, name=name, description=description, statuses=statuses, is_default_for_status=False)
        )
    await session.flush()
    return board


async def get_board(
    session: AsyncSession, actor: Actor, board_id: uuid.UUID, filters: TaskFilters, per_column: int
) -> BoardDetailResponse:
    """
    The board's columns, each with its full count and estimate total, whether it is past its
    limit, and its first `per_column` cards in board order. Cards are only tasks the caller may
    see, and the task list's filters narrow them.
    """
    board = await _get_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    base = _with_items(tasks._filtered_tasks(actor.organization_id, actor.user_id, filters).where(_board_tasks(board)), board)

    built: list[tuple[BoardColumn, int, int, list[Task]]] = []
    for column in layout.columns:
        query = base.where(_in_column(layout, column))
        totals = query.subquery()
        count, estimate = (
            await session.execute(select(func.count(), func.coalesce(func.sum(totals.c.estimate_minutes), 0)).select_from(totals))
        ).one()
        rows = list((await session.scalars(query.order_by(*_card_order(column)).limit(per_column))).all())
        built.append((column, count, int(estimate or 0), rows))

    responses = iter(await tasks._task_responses(session, [task for *_, rows in built for task in rows]))
    return BoardDetailResponse(
        **_summary(board).model_dump(),
        can_configure=await _may_configure(session, actor, board),
        uncovered_statuses=layout.uncovered(),
        columns=[
            BoardColumnView(
                **_column_response(column).model_dump(),
                count=count,
                estimate_minutes_total=estimate,
                over_limit=column.wip_limit is not None and count > column.wip_limit,
                tasks=[next(responses) for _ in rows],
                has_more=count > len(rows),
            )
            for column, count, estimate, rows in built
        ],
    )


async def update_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardUpdate, if_match: Optional[str]) -> BoardSummary:
    board = await _configurable_board(session, actor, board_id)
    check_if_match(if_match, board.version)
    board.name = data.name
    _touch(board)
    await session.flush()
    return _summary(board)


# --- Columns ----------------------------------------------------------------------------


async def _clear_other_defaults(session: AsyncSession, layout: _Layout, column: BoardColumn) -> None:
    """One default column per status: a column marked default takes its statuses from the others."""
    if not column.is_default_for_status:
        return
    for other in layout.columns:
        if other.id != column.id and other.is_default_for_status and set(other.statuses or []) & set(column.statuses or []):
            other.is_default_for_status = False


async def create_column(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardColumnCreate) -> BoardColumnResponse:
    """A new column at the end of the board."""
    board = await _configurable_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    column = BoardColumn(
        board_id=board.id,
        seq=max((c.seq for c in layout.columns), default=0) + 1,
        name=data.name,
        description=data.description,
        color=data.color,
        statuses=list(data.statuses),
        wip_limit=data.wip_limit,
        is_default_for_status=data.is_default_for_status,
    )
    session.add(column)
    await session.flush()
    await _clear_other_defaults(session, layout, column)
    _touch(board)
    await session.flush()
    return _column_response(column)


async def update_column(
    session: AsyncSession, actor: Actor, board_id: uuid.UUID, column_id: uuid.UUID, data: BoardColumnUpdate
) -> BoardColumnResponse:
    board = await _configurable_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    column = layout.column(column_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("name", "statuses", "is_default_for_status") and value is None:
            raise ValidationFailedError(field, "Can't be empty")
        setattr(column, field, list(value) if field == "statuses" else value)
    await _clear_other_defaults(session, layout, column)
    _touch(board)
    await session.flush()
    return _column_response(column)


async def delete_column(session: AsyncSession, actor: Actor, board_id: uuid.UUID, column_id: uuid.UUID) -> None:
    """Removes the column; its cards go back to their statuses' default columns."""
    board = await _configurable_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    column = layout.column(column_id)
    if len(layout.columns) == 1:
        raise LastBoardColumnError()
    await session.execute(delete(BoardItem).where(BoardItem.board_id == board.id, BoardItem.column_id == column.id))
    await session.delete(column)
    _touch(board)
    await session.flush()


async def reorder_columns(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardColumnOrder) -> list[BoardColumnResponse]:
    board = await _configurable_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    if sorted(map(str, data.column_ids)) != sorted(str(c.id) for c in layout.columns):
        raise ValidationFailedError("column_ids", "List every column of the board once")
    by_id = {c.id: c for c in layout.columns}
    for seq, column_id in enumerate(data.column_ids, start=1):
        by_id[column_id].seq = seq
    _touch(board)
    await session.flush()
    return [_column_response(by_id[column_id]) for column_id in data.column_ids]


# --- Cards ------------------------------------------------------------------------------


def board_step(status: str, has_assignee: bool, targets: set[str]) -> Optional[str]:
    """
    The task's step that takes it from `status` into a column holding `targets`, or None when no
    single step does. The step's own rules (who may take it) are checked when it runs.
    """
    if "in_progress" in targets:
        if status == "blocked":
            return "unblock"
        if status in ("assigned", "rework"):
            return "start"
        if status in ("draft", "open") and not has_assignee:
            return "claim_start"
    if status in ("submitted", "in_review"):
        if "done" in targets:
            return "approve"
        if "rework" in targets:
            return "send_back"
    if status in ("in_progress", "rework") and targets & {"submitted", "in_review", "done"}:
        return "submit"
    if "blocked" in targets and status in ("open", "assigned", "in_progress", "rework"):
        return "block"
    return None


async def _card(session: AsyncSession, actor: Actor, board: Board, task_id: uuid.UUID):
    """The task's status, assignee and version, if it is on this board and the caller may see it.

    Only these columns are read: claiming locks and re-reads the task, and an object loaded
    earlier would hand back a stale copy (services/tasks.py `claim_task`).
    """
    visible = tasks._filtered_tasks(actor.organization_id, actor.user_id, TaskFilters(view=await task_view(session, actor)))
    row = (
        await session.execute(
            visible.where(Task.id == task_id, _board_tasks(board)).with_only_columns(Task.status, Task.assignee_user_id, Task.version)
        )
    ).one_or_none()
    if row is None:
        raise TaskNotFoundError(str(task_id))
    return row


async def _take_step(
    session: AsyncSession, actor: Actor, people: PeopleDirectory, task_id: uuid.UUID, step: str, if_match: Optional[str]
) -> None:
    org_id = actor.organization_id
    if step in _STEPS_NEEDING_INPUT:
        raise BoardMoveNeedsInputError(step)
    if step == "claim_start":
        claimed = await tasks.claim_task(session, org_id, actor.user_id, task_id, if_match, people)
        await tasks.start_task(session, org_id, actor.user_id, task_id, f'"{claimed.version}"')
    elif step == "start":
        await tasks.start_task(session, org_id, actor.user_id, task_id, if_match)
    elif step == "unblock":
        await tasks.unblock_task(session, org_id, actor, task_id, if_match)


async def place_item(
    session: AsyncSession,
    actor: Actor,
    people: PeopleDirectory,
    board_id: uuid.UUID,
    task_id: uuid.UUID,
    data: BoardItemPlace,
    if_match: Optional[str],
) -> BoardItemResponse:
    """
    Put a card in a column, after or before another card (neither: at the top). If the column
    doesn't hold the task's status, the task takes the step there first. If-Match is the task's
    version, so a card moves only from the status the person saw.
    """
    board = await _get_board(session, actor, board_id)
    layout = await _layout(session, board.id)
    column = layout.column(data.column_id)
    status, assignee, version = await _card(session, actor, board, task_id)
    check_if_match(if_match, version)

    targets = set(column.statuses or [])
    if status not in targets:
        step = board_step(status, assignee is not None, targets)
        if step is None:
            raise BoardMoveNotAllowedError(status, sorted(targets))
        await _take_step(session, actor, people, task_id, step, if_match)

    rank = await _place(session, board, layout, column, task_id, data.after_task_id, data.before_task_id)
    task = await tasks._get_task(session, actor.organization_id, task_id)
    await session.flush()
    return BoardItemResponse(column_id=column.id, rank=rank, task=(await tasks._task_responses(session, [task]))[0])


async def _column_cards(session: AsyncSession, board: Board, layout: _Layout, column: BoardColumn, leaving_out: uuid.UUID):
    """Every card in the column in board order, (task id, rank here), whoever may see them: ranks are shared."""
    query = _with_items(select(Task.id, _rank_in(column)).select_from(Task), board).where(
        Task.organization_id == board.organization_id, _board_tasks(board), _in_column(layout, column), Task.id != leaving_out
    )
    return list((await session.execute(query.order_by(*_card_order(column)))).all())


async def _place(
    session: AsyncSession,
    board: Board,
    layout: _Layout,
    column: BoardColumn,
    task_id: uuid.UUID,
    after_task_id: Optional[uuid.UUID],
    before_task_id: Optional[uuid.UUID],
) -> str:
    """The card's new rank in the column; the column is renumbered when no key fits between its neighbours."""
    cards = await _column_cards(session, board, layout, column, task_id)
    ids = [card_id for card_id, _ in cards]
    index = 0
    if after_task_id is not None:
        if after_task_id not in ids:
            raise ValidationFailedError("after_task_id", "That card isn't in this column")
        index = ids.index(after_task_id) + 1
    elif before_task_id is not None:
        if before_task_id not in ids:
            raise ValidationFailedError("before_task_id", "That card isn't in this column")
        index = ids.index(before_task_id)

    above = cards[index - 1][1] if index > 0 else None
    below = cards[index][1] if index < len(cards) else None
    # Ranked cards come first: a key fits when the card above has one (or there is none).
    if index == 0 or above is not None:
        rank = rank_between(above, below)
        if len(rank) <= MAX_RANK_LENGTH:
            await _save_item(session, board, column, task_id, rank)
            return rank

    order = [*ids[:index], task_id, *ids[index:]]
    # Renumber up to the last card that had a rank (or the one placed); the rest stay by urgency.
    last_ranked = max([index] + [i + (1 if i >= index else 0) for i, (_, r) in enumerate(cards) if r is not None])
    keys = spread_ranks(last_ranked + 1)
    for card_id, key in zip(order[: last_ranked + 1], keys):
        await _save_item(session, board, column, card_id, key)
    return keys[index]


async def _save_item(session: AsyncSession, board: Board, column: BoardColumn, task_id: uuid.UUID, rank: Optional[str]) -> None:
    item = await session.get(BoardItem, (board.id, task_id))
    if item is None:
        session.add(BoardItem(board_id=board.id, task_id=task_id, column_id=column.id, rank=rank))
        return
    item.column_id = column.id
    item.rank = rank
    item.updated_at = datetime.now(timezone.utc)


async def create_item(
    session: AsyncSession,
    actor: Actor,
    people: PeopleDirectory,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    data: BoardItemCreate,
) -> BoardItemResponse:
    """A new task of the board's project, saved in this column (below the cards placed by hand)."""
    board = await _get_board(session, actor, board_id)
    if board.work_unit_id is None:
        raise ValidationFailedError("board_id", "New tasks are added on a project's board")
    layout = await _layout(session, board.id)
    column = layout.column(column_id)
    if not set(column.statuses or []) & _NEW_TASK_STATUSES:
        raise ColumnTakesNoNewTasksError()
    project = await session.scalar(select(WorkUnit).where(WorkUnit.id == board.work_unit_id))
    # The same rules as POST /tasks: a task with no team is its creator's own.
    payload = await tasks.personal_task_rules(actor, data.as_task(board.work_unit_id, project.owning_unit_id), people)
    task = await tasks.create_task(session, actor.organization_id, actor.user_id, payload, people)
    await _save_item(session, board, column, task.id, None)
    await session.flush()
    return BoardItemResponse(column_id=column.id, rank=None, task=task)
