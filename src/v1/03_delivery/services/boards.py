"""
Project boards (like GitHub Projects): a project's work divided into modules, laid out in
columns the team names itself (Backlog, Ready, In progress, ...). A module is its own record:
moving it between columns or reordering it changes only the board, never a task. Tasks may be
linked to a module, and the module shows how many of them are done.

A customer's board is every one of the customer's project boards together, their columns
matched by name.

Reading a board needs the project read permission (and seeing the project); changing it, its
columns and modules, needs the project write permission or managing the project.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    BoardColumnNotFoundError,
    BoardModuleNotFoundError,
    BoardNotFoundError,
    LastBoardColumnError,
    PermissionDeniedError,
    TaskNotFoundError,
    TaskNotInProjectError,
    ValidationFailedError,
    WorkUnitNotFoundError,
)
from models.board import Board, BoardColumn, BoardModule, BoardModuleTask
from models.task import Task
from models.work_unit import WorkUnit
from schemas.boards import (
    BoardColumnCreate,
    BoardColumnOrder,
    BoardColumnResponse,
    BoardColumnUpdate,
    BoardColumnView,
    BoardDetailResponse,
    BoardSummary,
    BoardUpdate,
    CustomerBoardColumn,
    CustomerBoardProject,
    CustomerBoardResponse,
    ModuleCreate,
    ModuleDetailResponse,
    ModulePlace,
    ModuleResponse,
    ModuleTaskRef,
    ModuleUpdate,
)
from services.identity_client import Actor
from services.ranks import MAX_RANK_LENGTH, rank_between, spread_ranks
from services.refs import user_ref
import services.tasks as tasks
from services.tasks import TaskFilters
from services.versions import check_if_match
from services.views import project_view, task_view
from services.work_units import ensure_work_unit_visible, visible_work_units

# What a project's board starts with (GitHub Projects' columns).
DEFAULT_COLUMNS: list[tuple[str, str]] = [
    ("Backlog", "This item hasn't been started"),
    ("Ready", "This is ready to be picked up"),
    ("In progress", "This is actively being worked on"),
    ("In review", "This item is in review"),
    ("Done", "This has been completed"),
]
DEFAULT_BOARD_NAME = "Board"


# --- Loading and permissions -----------------------------------------------------------


async def _project_in_view(session: AsyncSession, actor: Actor, work_unit_id: uuid.UUID) -> WorkUnit:
    project = await session.scalar(
        select(WorkUnit).where(WorkUnit.id == work_unit_id, WorkUnit.organization_id == actor.organization_id)
    )
    if project is None:
        raise WorkUnitNotFoundError(str(work_unit_id))
    view = await project_view(session, actor)
    if view is not None:
        await ensure_work_unit_visible(session, actor.organization_id, work_unit_id, view)
    return project


async def _get_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID) -> tuple[Board, WorkUnit]:
    """The board and its project, if it is in the caller's organization and they may see the project."""
    board = await session.scalar(select(Board).where(Board.id == board_id, Board.organization_id == actor.organization_id))
    if board is None:
        raise BoardNotFoundError(str(board_id))
    try:
        project = await _project_in_view(session, actor, board.work_unit_id)
    except WorkUnitNotFoundError:
        raise BoardNotFoundError(str(board_id)) from None
    return board, project


def _may_edit(actor: Actor, project: WorkUnit) -> bool:
    """Project managers in general, and this project's own manager."""
    if actor.has(permissions.WORK_UNIT_WRITE):
        return True
    return project.manager_user_id is not None and project.manager_user_id == actor.user_id


async def _editable_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID) -> Board:
    board, project = await _get_board(session, actor, board_id)
    if not _may_edit(actor, project):
        raise PermissionDeniedError(permissions.WORK_UNIT_WRITE)
    return board


async def _columns(session: AsyncSession, board_id: uuid.UUID) -> list[BoardColumn]:
    query = select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.seq, BoardColumn.id)
    return list((await session.scalars(query)).all())


def _column_of(columns: list[BoardColumn], column_id: uuid.UUID) -> BoardColumn:
    found = next((c for c in columns if c.id == column_id), None)
    if found is None:
        raise BoardColumnNotFoundError(str(column_id))
    return found


async def _get_module(session: AsyncSession, board: Board, module_id: uuid.UUID) -> BoardModule:
    module = await session.scalar(select(BoardModule).where(BoardModule.id == module_id, BoardModule.board_id == board.id))
    if module is None:
        raise BoardModuleNotFoundError(str(module_id))
    return module


def _touch(record) -> None:
    record.version += 1
    record.updated_at = datetime.now(timezone.utc)


# --- Responses ----------------------------------------------------------------------------


def _summary(board: Board) -> BoardSummary:
    return BoardSummary(id=board.id, name=board.name, work_unit_id=board.work_unit_id, version=board.version)


def _column_response(column: BoardColumn) -> BoardColumnResponse:
    return BoardColumnResponse(id=column.id, seq=column.seq, name=column.name, description=column.description, wip_limit=column.wip_limit)


async def _task_counts(session: AsyncSession, module_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """Linked tasks per module, cancelled ones left out: (how many, how many done)."""
    if not module_ids:
        return {}
    rows = await session.execute(
        select(BoardModuleTask.module_id, func.count(), func.sum(case((Task.status == "done", 1), else_=0)))
        .join(Task, Task.id == BoardModuleTask.task_id)
        .where(BoardModuleTask.module_id.in_(module_ids), Task.status != "cancelled")
        .group_by(BoardModuleTask.module_id)
    )
    return {module_id: (count, int(done or 0)) for module_id, count, done in rows.all()}


def _module_response(module: BoardModule, work_unit_id: uuid.UUID, counts: tuple[int, int] = (0, 0)) -> ModuleResponse:
    return ModuleResponse(
        id=module.id,
        board_id=module.board_id,
        work_unit_id=work_unit_id,
        column_id=module.column_id,
        rank=module.rank,
        title=module.title,
        description=module.description,
        owner=user_ref(module.owner_user_id),
        estimate_minutes=module.estimate_minutes,
        due_on=module.due_on,
        priority=module.priority,
        labels=list(module.labels or []),
        task_count=counts[0],
        tasks_done=counts[1],
        version=module.version,
        created_at=module.created_at,
        updated_at=module.updated_at,
    )


async def _response_with_counts(session: AsyncSession, module: BoardModule, work_unit_id: uuid.UUID) -> ModuleResponse:
    counts = (await _task_counts(session, [module.id])).get(module.id, (0, 0))
    return _module_response(module, work_unit_id, counts)


async def _module_responses(
    session: AsyncSession, modules: list[BoardModule], work_unit_of: dict[uuid.UUID, uuid.UUID]
) -> list[ModuleResponse]:
    counts = await _task_counts(session, [m.id for m in modules])
    return [_module_response(m, work_unit_of[m.board_id], counts.get(m.id, (0, 0))) for m in modules]


async def _modules_of(session: AsyncSession, board_ids: list[uuid.UUID]) -> list[BoardModule]:
    if not board_ids:
        return []
    query = select(BoardModule).where(BoardModule.board_id.in_(board_ids)).order_by(BoardModule.rank, BoardModule.id)
    return list((await session.scalars(query)).all())


# --- Boards ---------------------------------------------------------------------------


async def list_boards(session: AsyncSession, actor: Actor, work_unit_id: uuid.UUID) -> list[BoardSummary]:
    """A project's boards; its board is made from the template the first time it's asked for."""
    await _project_in_view(session, actor, work_unit_id)
    query = select(Board).where(Board.organization_id == actor.organization_id, Board.work_unit_id == work_unit_id)
    boards = list((await session.scalars(query.order_by(Board.created_at, Board.id))).all())
    if not boards:
        boards = [await _create_default_board(session, actor, work_unit_id)]
    return [_summary(board) for board in boards]


async def _create_default_board(session: AsyncSession, actor: Actor, work_unit_id: uuid.UUID) -> Board:
    board = Board(organization_id=actor.organization_id, work_unit_id=work_unit_id, name=DEFAULT_BOARD_NAME, created_by=actor.user_id, version=1)
    session.add(board)
    await session.flush()
    for seq, (name, description) in enumerate(DEFAULT_COLUMNS, start=1):
        session.add(BoardColumn(board_id=board.id, seq=seq, name=name, description=description))
    await session.flush()
    return board


async def get_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID) -> BoardDetailResponse:
    """The board's columns, each with its modules in order, their count and estimate total, and its limit."""
    board, project = await _get_board(session, actor, board_id)
    columns = await _columns(session, board.id)
    modules = await _module_responses(session, await _modules_of(session, [board.id]), {board.id: board.work_unit_id})
    views = []
    for column in columns:
        in_column = [m for m in modules if m.column_id == column.id]
        views.append(
            BoardColumnView(
                **_column_response(column).model_dump(),
                count=len(in_column),
                estimate_minutes_total=sum(m.estimate_minutes or 0 for m in in_column),
                over_limit=column.wip_limit is not None and len(in_column) > column.wip_limit,
                modules=in_column,
            )
        )
    return BoardDetailResponse(**_summary(board).model_dump(), can_edit=_may_edit(actor, project), columns=views)


async def update_board(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardUpdate, if_match: Optional[str]) -> BoardSummary:
    board = await _editable_board(session, actor, board_id)
    check_if_match(if_match, board.version)
    board.name = data.name
    _touch(board)
    await session.flush()
    return _summary(board)


async def get_customer_board(session: AsyncSession, actor: Actor, client_id: uuid.UUID) -> CustomerBoardResponse:
    """
    The modules of every project of the customer the caller may see, in columns matched by name
    (in the order the projects' boards list them). Projects without a board yet have no modules.
    """
    query = select(WorkUnit).where(WorkUnit.organization_id == actor.organization_id, WorkUnit.client_id == client_id)
    view = await project_view(session, actor)
    if view is not None:
        query = query.where(visible_work_units(actor.organization_id, view))
    projects = {p.id: p for p in (await session.scalars(query.order_by(WorkUnit.created_at, WorkUnit.id))).all()}
    boards: list[Board] = []
    if projects:
        board_query = select(Board).where(Board.organization_id == actor.organization_id, Board.work_unit_id.in_(list(projects)))
        boards = list((await session.scalars(board_query.order_by(Board.created_at, Board.id))).all())
    columns_of = {board.id: await _columns(session, board.id) for board in boards}
    modules = await _module_responses(
        session, await _modules_of(session, [b.id for b in boards]), {b.id: b.work_unit_id for b in boards}
    )

    # One column per name, first seen first; a module goes under its own column's name.
    names: dict[str, str] = {}
    key_of_column: dict[uuid.UUID, str] = {}
    for board in boards:
        for column in columns_of[board.id]:
            key = column.name.strip().casefold()
            names.setdefault(key, column.name.strip())
            key_of_column[column.id] = key
    # Within a column: project by project, each in its own board order.
    project_order = {board.id: i for i, board in enumerate(boards)}
    modules.sort(key=lambda m: (project_order[m.board_id], m.rank, str(m.id)))
    grouped = {key: [m for m in modules if key_of_column.get(m.column_id) == key] for key in names}
    return CustomerBoardResponse(
        client_id=client_id,
        projects=[
            CustomerBoardProject(
                work_unit_id=board.work_unit_id,
                name=projects[board.work_unit_id].name,
                board_id=board.id,
                can_edit=_may_edit(actor, projects[board.work_unit_id]),
                columns=[_column_response(c) for c in columns_of[board.id]],
            )
            for board in boards
        ],
        columns=[
            CustomerBoardColumn(
                name=name,
                count=len(grouped[key]),
                estimate_minutes_total=sum(m.estimate_minutes or 0 for m in grouped[key]),
                modules=grouped[key],
            )
            for key, name in names.items()
        ],
    )


# --- Columns ----------------------------------------------------------------------------


async def create_column(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardColumnCreate) -> BoardColumnResponse:
    """A new column at the end of the board."""
    board = await _editable_board(session, actor, board_id)
    columns = await _columns(session, board.id)
    column = BoardColumn(
        board_id=board.id,
        seq=max((c.seq for c in columns), default=0) + 1,
        name=data.name.strip(),
        description=data.description,
        wip_limit=data.wip_limit,
    )
    session.add(column)
    _touch(board)
    await session.flush()
    return _column_response(column)


async def update_column(
    session: AsyncSession, actor: Actor, board_id: uuid.UUID, column_id: uuid.UUID, data: BoardColumnUpdate
) -> BoardColumnResponse:
    board = await _editable_board(session, actor, board_id)
    column = _column_of(await _columns(session, board.id), column_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "name":
            if value is None:
                raise ValidationFailedError("name", "Can't be empty")
            value = value.strip()
        setattr(column, field, value)
    _touch(board)
    await session.flush()
    return _column_response(column)


async def delete_column(session: AsyncSession, actor: Actor, board_id: uuid.UUID, column_id: uuid.UUID) -> None:
    """Removes the column; its modules go to the bottom of the first column left, in their order."""
    board = await _editable_board(session, actor, board_id)
    columns = await _columns(session, board.id)
    column = _column_of(columns, column_id)
    remaining = [c for c in columns if c.id != column.id]
    if not remaining:
        raise LastBoardColumnError()
    moving_query = select(BoardModule).where(BoardModule.column_id == column.id).order_by(BoardModule.rank, BoardModule.id)
    target = remaining[0]
    last = await _last_rank(session, target.id)
    for module in (await session.scalars(moving_query)).all():
        last = rank_between(last, None)
        module.column_id = target.id
        module.rank = last
    await session.flush()
    await session.delete(column)
    _touch(board)
    await session.flush()


async def reorder_columns(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: BoardColumnOrder) -> list[BoardColumnResponse]:
    board = await _editable_board(session, actor, board_id)
    columns = await _columns(session, board.id)
    if sorted(map(str, data.column_ids)) != sorted(str(c.id) for c in columns):
        raise ValidationFailedError("column_ids", "List every column of the board once")
    by_id = {c.id: c for c in columns}
    for seq, column_id in enumerate(data.column_ids, start=1):
        by_id[column_id].seq = seq
    _touch(board)
    await session.flush()
    return [_column_response(by_id[column_id]) for column_id in data.column_ids]


# --- Modules ----------------------------------------------------------------------------


async def _last_rank(session: AsyncSession, column_id: uuid.UUID) -> Optional[str]:
    return await session.scalar(select(func.max(BoardModule.rank)).where(BoardModule.column_id == column_id))


async def create_module(session: AsyncSession, actor: Actor, board_id: uuid.UUID, data: ModuleCreate) -> ModuleResponse:
    """A new module at the bottom of its column."""
    board = await _editable_board(session, actor, board_id)
    column = _column_of(await _columns(session, board.id), data.column_id)
    now = datetime.now(timezone.utc)
    module = BoardModule(
        organization_id=actor.organization_id,
        board_id=board.id,
        column_id=column.id,
        rank=rank_between(await _last_rank(session, column.id), None),
        title=data.title.strip(),
        description=data.description,
        owner_user_id=data.owner_user_id,
        estimate_minutes=data.estimate_minutes,
        due_on=data.due_on,
        priority=data.priority,
        labels=data.labels,
        created_by=actor.user_id,
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(module)
    await session.flush()
    return _module_response(module, board.work_unit_id)


async def get_module(session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID) -> ModuleDetailResponse:
    """The module with its linked tasks (the ones the caller may see), open ones first."""
    board, _ = await _get_board(session, actor, board_id)
    module = await _get_module(session, board, module_id)
    visible = tasks._filtered_tasks(actor.organization_id, actor.user_id, TaskFilters(view=await task_view(session, actor)))
    linked_query = (
        visible.join(BoardModuleTask, BoardModuleTask.task_id == Task.id)
        .where(BoardModuleTask.module_id == module.id)
        .order_by(case((Task.status.in_(["done", "cancelled"]), 1), else_=0), *tasks._work_order())
    )
    linked = (await session.scalars(linked_query)).all()
    summary = await _response_with_counts(session, module, board.work_unit_id)
    return ModuleDetailResponse(
        **summary.model_dump(),
        tasks=[
            ModuleTaskRef(id=t.id, code=t.code, title=t.title, status=t.status, assignee=user_ref(t.assignee_user_id), due_at=t.due_at)
            for t in linked
        ],
    )


async def update_module(
    session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID, data: ModuleUpdate, if_match: Optional[str]
) -> ModuleResponse:
    board = await _editable_board(session, actor, board_id)
    module = await _get_module(session, board, module_id)
    check_if_match(if_match, module.version)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("title", "priority", "labels") and value is None:
            raise ValidationFailedError(field, "Can't be empty")
        setattr(module, field, value.strip() if field == "title" else value)
    _touch(module)
    await session.flush()
    return await _response_with_counts(session, module, board.work_unit_id)


async def delete_module(session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID) -> None:
    """Removes the module; its tasks stay as they are, just no longer linked."""
    board = await _editable_board(session, actor, board_id)
    module = await _get_module(session, board, module_id)
    await session.execute(delete(BoardModuleTask).where(BoardModuleTask.module_id == module.id))
    await session.delete(module)
    await session.flush()


async def place_module(session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID, data: ModulePlace) -> ModuleResponse:
    """Put a module in a column, after or before another module there (neither: at the bottom)."""
    board = await _editable_board(session, actor, board_id)
    column = _column_of(await _columns(session, board.id), data.column_id)
    module = await _get_module(session, board, module_id)
    others_query = (
        select(BoardModule.id, BoardModule.rank)
        .where(BoardModule.column_id == column.id, BoardModule.id != module.id)
        .order_by(BoardModule.rank, BoardModule.id)
    )
    others = list((await session.execute(others_query)).all())
    ids = [other_id for other_id, _ in others]
    index = len(ids)
    if data.after_module_id is not None:
        if data.after_module_id not in ids:
            raise ValidationFailedError("after_module_id", "That module isn't in this column")
        index = ids.index(data.after_module_id) + 1
    elif data.before_module_id is not None:
        if data.before_module_id not in ids:
            raise ValidationFailedError("before_module_id", "That module isn't in this column")
        index = ids.index(data.before_module_id)

    module.column_id = column.id
    above = others[index - 1][1] if index > 0 else None
    below = others[index][1] if index < len(others) else None
    if above is None or below is None or above < below:
        rank = rank_between(above, below)
        if len(rank) <= MAX_RANK_LENGTH:
            module.rank = rank
            return await _placed(session, board, module)
    # No key fits between the neighbours (equal keys, or keys grown long): number the column afresh.
    order = [*ids[:index], module.id, *ids[index:]]
    rows = {m.id: m for m in (await session.scalars(select(BoardModule).where(BoardModule.id.in_(order)))).all()}
    for row_id, key in zip(order, spread_ranks(len(order))):
        rows[row_id].rank = key
    return await _placed(session, board, module)


async def _placed(session: AsyncSession, board: Board, module: BoardModule) -> ModuleResponse:
    module.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return await _response_with_counts(session, module, board.work_unit_id)


# --- Linked tasks ---------------------------------------------------------------------------


async def link_task(session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID, task_id: uuid.UUID) -> ModuleResponse:
    """Link one of the project's tasks to the module (taking it from any other module). The task doesn't change."""
    board = await _editable_board(session, actor, board_id)
    module = await _get_module(session, board, module_id)
    visible = tasks._filtered_tasks(actor.organization_id, actor.user_id, TaskFilters(view=await task_view(session, actor)))
    row = (await session.execute(visible.where(Task.id == task_id).with_only_columns(Task.work_unit_id))).one_or_none()
    if row is None:
        raise TaskNotFoundError(str(task_id))
    if row.work_unit_id != board.work_unit_id:
        raise TaskNotInProjectError()
    link = await session.get(BoardModuleTask, task_id)
    if link is None:
        session.add(BoardModuleTask(task_id=task_id, module_id=module.id, linked_by=actor.user_id, linked_at=datetime.now(timezone.utc)))
    else:
        link.module_id = module.id
        link.linked_by = actor.user_id
        link.linked_at = datetime.now(timezone.utc)
    await session.flush()
    return await _response_with_counts(session, module, board.work_unit_id)


async def unlink_task(session: AsyncSession, actor: Actor, board_id: uuid.UUID, module_id: uuid.UUID, task_id: uuid.UUID) -> None:
    board = await _editable_board(session, actor, board_id)
    module = await _get_module(session, board, module_id)
    await session.execute(delete(BoardModuleTask).where(BoardModuleTask.module_id == module.id, BoardModuleTask.task_id == task_id))
    await session.flush()
