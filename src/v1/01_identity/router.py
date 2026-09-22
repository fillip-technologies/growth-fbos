from fastapi import APIRouter
from routes.auth import router as auth_router
from routes.calendars import router as calendars_router
from routes.org_units import router as org_units_router
from routes.rbac import (
    internal_router,
    permissions_router,
    role_assignments_router,
    roles_router,
)
from routes.users import router as users_router
from routes.verticals import (
    field_definitions_router,
    object_types_router,
    vertical_packs_router,
)

core_router = APIRouter()
core_router.include_router(auth_router, prefix="/auth", tags=["auth"])
core_router.include_router(users_router, prefix="/users", tags=["users"])
core_router.include_router(org_units_router, prefix="/org-units", tags=["org-units"])
core_router.include_router(roles_router, prefix="/roles", tags=["roles"])
core_router.include_router(permissions_router, prefix="/permissions", tags=["permissions"])
core_router.include_router(role_assignments_router, prefix="/role-assignments", tags=["role-assignments"])
core_router.include_router(calendars_router, prefix="/calendars", tags=["calendars"])
core_router.include_router(object_types_router, prefix="/object-types", tags=["object-types"])
core_router.include_router(field_definitions_router, prefix="/field-definitions", tags=["field-definitions"])
core_router.include_router(vertical_packs_router, prefix="/vertical-packs", tags=["vertical-packs"])
core_router.include_router(internal_router, prefix="/internal", tags=["internal"])





# Mount both /v1 and /api/identity/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/identity/v1")
