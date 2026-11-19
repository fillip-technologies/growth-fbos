"""
Project boards (services/boards.py): a project's work divided into modules, in columns the team
names. Reading needs the project read permission; changing a board (columns, modules, linked
tasks) needs the project write permission or managing the project, checked in the service.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.boards as service
from dependencies import CurrentActor, DatabaseSession, require_permission
from schemas.boards import (
    BoardColumnCreate,
    BoardColumnOrder,
    BoardColumnResponse,
    BoardColumnUpdate,
    BoardDetailResponse,
    BoardSummary,
    BoardUpdate,
    CustomerBoardResponse,
    ModuleCreate,
    ModuleDetailResponse,
    ModulePlace,
    ModuleResponse,
    ModuleUpdate,
)
from schemas.common import PageMeta, PageResponse

router = APIRouter(tags=["boards"])

CAN_READ = Depends(require_permission(permissions.WORK_UNIT_READ))


# --- Boards --------------------------------------------------------------------------


@router.get("/boards", response_model=PageResponse[BoardSummary], dependencies=[CAN_READ])
async def list_boards(
    session: DatabaseSession, actor: CurrentActor, work_unit_id: uuid.UUID = Query(..., description="The project")
) -> PageResponse[BoardSummary]:
    """A project's boards; its board is made the first time it's asked for."""
    boards = await service.list_boards(session, actor, work_unit_id)
    await session.commit()
    return PageResponse(data=boards, page=PageMeta(next_cursor=None, has_more=False, limit=len(boards)))


@router.get("/boards/{board_id}", response_model=BoardDetailResponse, dependencies=[CAN_READ])
async def get_board(board_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, response: Response) -> BoardDetailResponse:
    """The board's columns, each with its modules in order, their count, estimate total and limit."""
    board = await service.get_board(session, actor, board_id)
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
    """Rename the board."""
    board = await service.update_board(session, actor, board_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{board.version}"'
    return board


@router.get("/customer-boards/{client_id}", response_model=CustomerBoardResponse, dependencies=[CAN_READ])
async def get_customer_board(client_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> CustomerBoardResponse:
    """The modules of all the customer's projects you may see, in columns matched by name."""
    return await service.get_customer_board(session, actor, client_id)


# --- Columns ---------------------------------------------------------------------------


@router.post("/boards/{board_id}/columns", response_model=BoardColumnResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def create_column(board_id: uuid.UUID, payload: BoardColumnCreate, session: DatabaseSession, actor: CurrentActor) -> BoardColumnResponse:
    """Add a column at the end of the board."""
    column = await service.create_column(session, actor, board_id, payload)
    await session.commit()
    return column


@router.put("/boards/{board_id}/columns/order", response_model=list[BoardColumnResponse], dependencies=[CAN_READ])
async def reorder_columns(
    board_id: uuid.UUID, payload: BoardColumnOrder, session: DatabaseSession, actor: CurrentActor
) -> list[BoardColumnResponse]:
    """Put the board's columns in a new order."""
    columns = await service.reorder_columns(session, actor, board_id, payload)
    await session.commit()
    return columns


@router.patch("/boards/{board_id}/columns/{column_id}", response_model=BoardColumnResponse, dependencies=[CAN_READ])
async def update_column(
    board_id: uuid.UUID, column_id: uuid.UUID, payload: BoardColumnUpdate, session: DatabaseSession, actor: CurrentActor
) -> BoardColumnResponse:
    """Rename a column, or change its description or item limit."""
    column = await service.update_column(session, actor, board_id, column_id, payload)
    await session.commit()
    return column


@router.delete("/boards/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def delete_column(board_id: uuid.UUID, column_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> None:
    """Remove a column; its modules go to the bottom of the first column left."""
    await service.delete_column(session, actor, board_id, column_id)
    await session.commit()


# --- Modules ---------------------------------------------------------------------------


@router.post("/boards/{board_id}/modules", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def create_module(
    board_id: uuid.UUID, payload: ModuleCreate, session: DatabaseSession, actor: CurrentActor, response: Response
) -> ModuleResponse:
    """Add a module at the bottom of a column."""
    module = await service.create_module(session, actor, board_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{module.version}"'
    return module


@router.get("/boards/{board_id}/modules/{module_id}", response_model=ModuleDetailResponse, dependencies=[CAN_READ])
async def get_module(
    board_id: uuid.UUID, module_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, response: Response
) -> ModuleDetailResponse:
    """A module with its linked tasks."""
    module = await service.get_module(session, actor, board_id, module_id)
    response.headers["ETag"] = f'"{module.version}"'
    return module


@router.patch("/boards/{board_id}/modules/{module_id}", response_model=ModuleResponse, dependencies=[CAN_READ])
async def update_module(
    board_id: uuid.UUID,
    module_id: uuid.UUID,
    payload: ModuleUpdate,
    session: DatabaseSession,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ModuleResponse:
    """Change a module's title, description, owner, estimate, due date, priority or labels."""
    module = await service.update_module(session, actor, board_id, module_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{module.version}"'
    return module


@router.delete("/boards/{board_id}/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def delete_module(board_id: uuid.UUID, module_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> None:
    """Remove a module; its tasks stay as they are."""
    await service.delete_module(session, actor, board_id, module_id)
    await session.commit()


@router.put("/boards/{board_id}/modules/{module_id}/position", response_model=ModuleResponse, dependencies=[CAN_READ])
async def place_module(
    board_id: uuid.UUID, module_id: uuid.UUID, payload: ModulePlace, session: DatabaseSession, actor: CurrentActor
) -> ModuleResponse:
    """Put a module in a column, after or before another one (neither: at the bottom)."""
    module = await service.place_module(session, actor, board_id, module_id, payload)
    await session.commit()
    return module


@router.put("/boards/{board_id}/modules/{module_id}/tasks/{task_id}", response_model=ModuleResponse, dependencies=[CAN_READ])
async def link_task(
    board_id: uuid.UUID, module_id: uuid.UUID, task_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor
) -> ModuleResponse:
    """Link one of the project's tasks to the module (a task belongs to one module at most)."""
    module = await service.link_task(session, actor, board_id, module_id, task_id)
    await session.commit()
    return module


@router.delete("/boards/{board_id}/modules/{module_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def unlink_task(board_id: uuid.UUID, module_id: uuid.UUID, task_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor) -> None:
    """Unlink a task from the module; the task doesn't change."""
    await service.unlink_task(session, actor, board_id, module_id, task_id)
    await session.commit()
