from fastapi import APIRouter

from routes.activities import router as activities_router
from routes.clients import router as clients_router
from routes.collections import router as collections_router
from routes.contracts import router as contracts_router
from routes.invoices import router as invoices_router
from routes.leads import router as leads_router
from routes.offerings import router as offerings_router
from routes.opportunities import router as opportunities_router
from routes.payments import router as payments_router
from routes.quotations import router as quotations_router
from routes.webhooks import router as webhooks_router

core_router = APIRouter()
core_router.include_router(clients_router)
core_router.include_router(offerings_router)
core_router.include_router(leads_router)
core_router.include_router(opportunities_router)
core_router.include_router(quotations_router)
core_router.include_router(contracts_router)
core_router.include_router(activities_router)
core_router.include_router(invoices_router)
core_router.include_router(payments_router)
core_router.include_router(collections_router)
core_router.include_router(webhooks_router)

# Mount both /v1 and /api/revenue/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/revenue/v1")
