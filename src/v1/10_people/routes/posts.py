import uuid

from fastapi import APIRouter, Depends, Query

import permissions
import services.posts as posts
from dependencies import CurrentActor, DatabaseSession, require_permission
from schemas.post import OrgChart, PostsReport, WorkerPostList
from services.worker_documents import ensure_worker

router = APIRouter(tags=["posts"])

CAN_READ = Depends(require_permission(permissions.EMPLOYEE_READ))


@router.get("/workers/{worker_id}/posts", response_model=WorkerPostList, dependencies=[CAN_READ])
async def list_worker_posts(
    session: DatabaseSession,
    actor: CurrentActor,
    worker_id: uuid.UUID,
    include_ended: bool = Query(False, description="Also show earlier versions and ended posts"),
):
    """The jobs this person holds: the primary post first, then the others. Posts change through role changes."""
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    found = await posts.list_posts(session, worker, include_ended=include_ended)
    return {"data": await posts.to_responses(session, actor, found)}


@router.get("/org-chart", response_model=OrgChart, dependencies=[CAN_READ])
async def get_org_chart(session: DatabaseSession, actor: CurrentActor):
    """Who reports to whom: the primary manager is the solid line, the managers of extra posts are dotted lines."""
    return await posts.org_chart(session, actor.organization_id)


@router.get("/reports/posts", response_model=PostsReport, dependencies=[CAN_READ])
async def get_posts_report(session: DatabaseSession, actor: CurrentActor):
    """Posts and FTE by department: people, posts by kind, FTE allocated, and the seats' budget against use."""
    return await posts.posts_report(session, actor.organization_id)
