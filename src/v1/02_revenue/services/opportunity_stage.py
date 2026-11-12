"""
The opportunity's stage follows its proposal and quotations: sending one moves it to
"proposal", the customer asking for changes to "negotiation", accepting a quotation to "won".
"""

from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.opportunity import Opportunity

# The open stages, in the order a deal moves through them.
OPEN_STAGES = ("open", "qualification", "proposal", "negotiation")


async def advance(session: AsyncSession, opportunity_id: Optional[uuid.UUID], stage: str) -> None:
    """Moves the opportunity forward to `stage`, never back, and never once it is won or lost."""
    if not opportunity_id:
        return
    opp = await session.get(Opportunity, opportunity_id)
    if not opp or opp.status not in OPEN_STAGES or OPEN_STAGES.index(opp.status) >= OPEN_STAGES.index(stage):
        return
    opp.status = stage
    opp.version += 1
