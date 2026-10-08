from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from schemas.common import UnitRef, UserRef

# queue: the work waits until someone takes it or a manager assigns it; round_robin: the team's
# people take turns; least_busy: whoever has the fewest open tasks gets it.
AssignmentPolicyName = Literal["queue", "round_robin", "least_busy"]


class AssignmentPolicyResponse(BaseModel):
    unit: UnitRef
    policy: AssignmentPolicyName
    # Send it back as If-Match to change the policy (0 for a team that has none yet).
    version: int
    updated_at: datetime
    updated_by: Optional[UserRef] = None


class AssignmentPoliciesResponse(BaseModel):
    """The teams that have a policy; any other team leaves new work in its queue."""

    data: list[AssignmentPolicyResponse]


class AssignmentPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: AssignmentPolicyName
