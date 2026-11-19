"""
Kanban boards for a project or a customer (services/boards.py). Reading a board and moving its
cards need the task read permission, and each move takes the task's own step rules; setting a
board up (its name and columns) needs the task managers' permission, or managing its project.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.boards as service
from dependencies import CurrentActor, DatabaseSession, People, require_permission
from routes.tasks import Filters
from schemas.boards import (
    BoardColumnCreate,
    BoardColumnOrder,
    BoardColumnResponse,
    BoardColumnUpdate,
    BoardDetailResponse,
    BoardItemCreate,
    BoardItemPlace,
    BoardItemResponse,
    BoardSummary,
    BoardUpdate,
)
from schemas.common import PageMeta, PageResponse

router = APIRouter(tags=["boards"])

CAN_READ = Depends(require_permission(permissions.TASK_READ))
CAN_WRITE = Depends(require_permission(permissions.TASK_WRITE))


@router.get("/boards", response_model=PageResponse[BoardSummary], dependencies=[CAN_READ])
async def list_boards(
    session: DatabaseSession,
    actor: CurrentActor,
    work_unit_id: Optional[uuid.UUID] = Query(None, description="A project's boards"),
    client_id: Optional[uuid.UUID] = Query(None, description="A customer's boards, over all its projects"),
) -> PageResponse[BoardSummary]:
    """A project's or a customer's boards; the default board is made the first time it's asked for."""
    boards = await service.list_boards(session, actor, work_unit_id, client_id)
    await session.commit()
    return PageResponse(data=boards, page=PageMeta(next_cursor=None, has_more=False, limit=len(boards)))


@router.get("/boards/{board_id}", response_model=BoardDetailResponse, dependencies=[CAN_READ])
async def get_board(
    board_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    filters: Filters,
    response: Response,
    per_column: int = Query(50, ge=1, le=100),
) -> BoardDetailResponse:
    """The board's columns with their counts, estimate totals and limits, and their cards in board order."""
    board = await service.get_board(session, actor, board_id, filters, per_column)
    response.headers["ETag"] = f'"{board.version}"'
    return board


@router.patch("/boards/{board_id}", response_model=BoardSummary, dependencies=[CAN_READ])
async def update_board(
    board_id: uuid.UUID,
    payload: BoardUpdate,
    session: DatabaseSession,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> BoardSummary:
    """Rename the board (task managers, or the project's manager)."""
    board = await service.update_board(session, actor, board_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{board.version}"'
    return board


@router.post("/boards/{board_id}/columns", response_model=BoardColumnResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def create_column(
    board_id: uuid.UUID, payload: BoardColumnCreate, session: DatabaseSession, actor: CurrentActor
) -> BoardColumnResponse:
    """Add a column at the end of the board (task managers, or the project's manager)."""
    column = await service.create_column(session, actor, board_id, payload)
    await session.commit()
    return column


@router.put("/boards/{board_id}/columns/order", response_model=list[BoardColumnResponse], dependencies=[CAN_READ])
async def reorder_columns(
    board_id: uuid.UUID, payload: BoardColumnOrder, session: DatabaseSession, actor: CurrentActor
) -> list[BoardColumnResponse]:
    """Put the board's columns in a new order (task managers, or the project's manager)."""
    columns = await service.reorder_columns(session, actor, board_id, payload)
    await session.commit()
    return columns


@router.patch("/boards/{board_id}/columns/{column_id}", response_model=BoardColumnResponse, dependencies=[CAN_READ])
async def update_column(
    board_id: uuid.UUID, column_id: uuid.UUID, payload: BoardColumnUpdate, session: DatabaseSession, actor: CurrentActor
) -> BoardColumnResponse:
    """Rename a column, or change its description, statuses or limit (task managers, or the project's manager)."""
    column = await service.update_column(session, actor, board_id, column_id, payload)
    await session.commit()
    return column


@router.delete("/boards/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def delete_column(board_id: uuid.UUID, column_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> None:
    """Remove a column; its cards go to their statuses' default columns (task managers, or the project's manager)."""
    await service.delete_column(session, actor, board_id, column_id)
    await session.commit()


@router.put("/boards/{board_id}/items/{task_id}", response_model=BoardItemResponse, dependencies=[CAN_READ])
async def place_item(
    board_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: BoardItemPlace,
    session: DatabaseSession,
    actor: CurrentActor,
    people: People,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match", description="The task's version"),
) -> BoardItemResponse:
    """
    Put a card in a column and a place in it. A column with another status takes the task's step
    there (its assignee or a task manager, as on the task); BOARD_MOVE_NEEDS_INPUT when that step
    asks for more first.
    """
    item = await service.place_item(session, actor, people, board_id, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{item.task.version}"'
    return item


@router.post(
    "/boards/{board_id}/columns/{column_id}/items",
    response_model=BoardItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_item(
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    payload: BoardItemCreate,
    session: DatabaseSession,
    actor: CurrentActor,
    people: People,
    response: Response,
) -> BoardItemResponse:
    """Add a task of the board's project straight into a column for work not yet started."""
    item = await service.create_item(session, actor, people, board_id, column_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{item.task.version}"'
    return item
