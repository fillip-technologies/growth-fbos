from fastapi import APIRouter

from routes.attendance import router as attendance_router
from routes.internal import router as internal_router
from routes.leaves import router as leaves_router
from routes.payroll import router as payroll_router
from routes.positions import router as positions_router
from routes.progression import router as progression_router
from routes.recruitment import router as recruitment_router
from routes.separation import router as separation_router
from routes.worker_documents import router as worker_documents_router
from routes.workers import router as workers_router

core_router = APIRouter()
core_router.include_router(positions_router)
core_router.include_router(recruitment_router)
core_router.include_router(workers_router)
core_router.include_router(worker_documents_router)
core_router.include_router(internal_router)
core_router.include_router(attendance_router)
core_router.include_router(leaves_router)
core_router.include_router(payroll_router)
core_router.include_router(progression_router)
core_router.include_router(separation_router)







# Mount both /v1 and /api/people/v1 for complete gateway & direct compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/people/v1")
