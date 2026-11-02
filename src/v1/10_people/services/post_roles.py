"""
The Identity roles a post gives.

A post lists the roles it gives (`WorkerPost.role_codes`). A role change moves that list, and the
sync tells Identity, so an approved promotion changes what the person can do. This module checks the
roles against Identity, names them, and works out which are new and whether the requester could grant
them. A role People may not grant (a system or admin role) is refused unless the post already has it.
"""

import uuid
from typing import Any, Optional

from exceptions import ValidationFailedError
from services.identity_client import IdentityClient, RoleOption

SpecDict = dict[str, Any]  # {"role_code", "scope", "name"}


def spec_key(spec: SpecDict) -> tuple[str, str]:
    scope = spec.get("scope") or "organization"
    return spec["role_code"].lower(), f"unit:{spec.get('unit_id')}" if scope == "unit" else scope


def title_from_roles(specs: list[SpecDict]) -> Optional[str]:
    """The title the roles give: their names joined, as `designation.designation_from_roles` does."""
    names = [(spec.get("name") or spec["role_code"]).strip() for spec in specs]
    return " / ".join(name for name in names if name)[:255] or None


def same_roles(first: list[SpecDict], second: list[SpecDict]) -> bool:
    return {spec_key(spec) for spec in first} == {spec_key(spec) for spec in second}


def added_specs(current: list[SpecDict], wanted: list[SpecDict]) -> list[SpecDict]:
    """The roles in `wanted` that the post does not give yet."""
    held = {spec_key(spec) for spec in current}
    return [spec for spec in wanted if spec_key(spec) not in held]


async def resolve_specs(
    identity: IdentityClient, organization_id: uuid.UUID, wanted: list[SpecDict], current: list[SpecDict]
) -> list[SpecDict]:
    """
    `wanted` with each role's name filled in from Identity. Refuses a role that does not exist, one
    listed twice, and a new role People may not grant.
    """
    options: dict[str, RoleOption] = {role.code.lower(): role for role in await identity.list_roles(organization_id)}
    new_keys = {spec_key(spec) for spec in added_specs(current, wanted)}
    resolved: list[SpecDict] = []
    for spec in wanted:
        option = options.get(spec["role_code"].lower())
        if option is None:
            raise ValidationFailedError("new_role_codes", f"Unknown role '{spec['role_code']}'")
        if spec_key(spec) in {spec_key(done) for done in resolved}:
            raise ValidationFailedError("new_role_codes", f"'{option.name}' is listed twice")
        if spec_key(spec) in new_keys and not option.assignable_by_people:
            raise ValidationFailedError("new_role_codes", f"'{option.name}' cannot be given from People; grant it under Users")
        kept = {"unit_id": spec["unit_id"]} if spec.get("scope") == "unit" else {}
        resolved.append({"role_code": option.code, "scope": spec.get("scope") or "organization", "name": option.name, **kept})
    return resolved


async def roles_beyond_requester(
    identity: IdentityClient, organization_id: uuid.UUID, requester_user_id: uuid.UUID,
    added: list[SpecDict], department_id: Optional[uuid.UUID],
) -> list[str]:
    """The new roles the requester could not grant themselves; an Identity admin must approve those."""
    beyond: list[str] = []
    for scope, unit_id in (("organization", None), ("department", department_id)):
        codes = [spec["role_code"] for spec in added if (spec.get("scope") or "organization") == scope]
        if codes:
            beyond += await identity.roles_beyond_requester(organization_id, requester_user_id, codes, unit_id)
    return beyond
