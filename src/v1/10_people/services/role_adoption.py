"""
One-off: make the roles people hold today People's own.

Until now every role was granted by hand under Users, and People never removes those. If nothing is done,
a promotion would leave the person with the old role and the new one. This reads each employee's hand-granted
roles from Identity, asks Identity to mark them as People's (`source=people`, tied to the primary post), and
records them on the primary post. After that an approved role change replaces them. Roles granted by hand
later stay untouched. Repeating it finds nothing more to take over.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.worker import Worker
from models.worker_post import WorkerPost
import services.identity_sync as identity_sync
import services.post_roles as post_roles
import services.posts as posts
from services.identity_client import IdentityClient

logger = logging.getLogger("people.role_adoption")

IDENTITY_PAGE = 100  # most users Identity answers for in one call


@dataclass
class AdoptionReport:
    adopted: int = 0  # employees whose roles were taken over
    roles: int = 0  # roles taken over, in all
    skipped_no_roles: int = 0  # nothing held by hand
    notes: list[str] = field(default_factory=list)


def _spec(code: str, name: str, unit_id: Optional[uuid.UUID], post: WorkerPost) -> dict:
    if unit_id is None:
        return {"role_code": code, "scope": "organization", "name": name}
    if unit_id == post.unit_id:
        return {"role_code": code, "scope": "department", "name": name}
    return {"role_code": code, "scope": "unit", "unit_id": str(unit_id), "name": name}  # kept exactly as it was held


async def _candidates(session: AsyncSession, organization_id: Optional[uuid.UUID]) -> list[Worker]:
    query = select(Worker).where(Worker.user_id.is_not(None), Worker.status != "exited").order_by(Worker.created_at)
    if organization_id is not None:
        query = query.where(Worker.organization_id == organization_id)
    return list((await session.execute(query)).scalars())


async def adopt_current_roles(
    session: AsyncSession, identity: IdentityClient, organization_id: Optional[uuid.UUID] = None, dry_run: bool = False
) -> AdoptionReport:
    """Take over the hand-granted roles of every employee with a login. Commits after each employee, so it can be stopped and resumed."""
    report = AdoptionReport()
    workers = await _candidates(session, organization_id)
    names: dict[uuid.UUID, dict[str, str]] = {}  # per organization: role code (lowercase) -> name

    for start in range(0, len(workers), IDENTITY_PAGE):
        chunk = workers[start : start + IDENTITY_PAGE]
        for org in {w.organization_id for w in chunk}:
            group = [w for w in chunk if w.organization_id == org]
            page = await identity.list_employees(org, user_ids=[w.user_id for w in group], limit=len(group))
            held = {employee.id: [role.code for role in employee.roles] for employee in page.data}
            if org not in names:
                names[org] = {role.code.lower(): role.name for role in await identity.list_roles(org)}
            for worker in group:
                await _adopt_for(session, identity, worker, held.get(worker.user_id, []), names[org], report, dry_run)
    return report


async def _adopt_for(
    session: AsyncSession, identity: IdentityClient, worker: Worker, codes: list[str], names: dict[str, str],
    report: AdoptionReport, dry_run: bool,
) -> None:
    if not codes:
        report.skipped_no_roles += 1
        return
    primary = next((p for p in await posts.live_posts(session, worker) if p.post_type == posts.PRIMARY), None)
    if primary is None:
        report.notes.append(f"{worker.id}: no primary post, left as it is")
        return
    if dry_run:
        report.adopted += 1
        report.roles += len(codes)
        return

    outcome = await identity.adopt_roles(worker.organization_id, worker.user_id, codes, str(primary.post_ref))
    # Identity has already made these People's; recording them now is what keeps a later sync from taking them away.
    adopted = [_spec(code, names.get(code.lower(), code), unit_id, primary) for code, unit_id in outcome.adopted]
    held = {post_roles.spec_key(spec) for spec in primary.role_codes or []}  # roles a mapping already gave the post stay as they are
    primary.role_codes = [*(primary.role_codes or []), *(spec for spec in adopted if post_roles.spec_key(spec) not in held)]
    if outcome.missing:
        report.notes.append(f"{worker.id}: not adopted ({', '.join(outcome.missing)}): not held by hand any more")
    await identity_sync.queue_sync(session, worker)
    await session.commit()
    report.adopted += 1
    report.roles += len(outcome.adopted)
