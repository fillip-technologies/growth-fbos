from fastapi import APIRouter

from routes.activities import router as activities_router
from routes.client_services import router as client_services_router
from routes.billing_schedules import router as billing_schedules_router
from routes.client_tax_profiles import router as client_tax_profiles_router
from routes.clients import router as clients_router
from routes.collections import router as collections_router
from routes.contracts import router as contracts_router
from routes.finance_settings import router as finance_settings_router
from routes.internal import router as internal_router
from routes.invoices import router as invoices_router
from routes.leads import router as leads_router
from routes.offerings import router as offerings_router
from routes.opportunities import router as opportunities_router
from routes.payments import router as payments_router
from routes.quotations import router as quotations_router
from routes.receivables import router as receivables_router
from routes.tax import router as tax_router
from routes.tax_registrations import router as tax_registrations_router
from routes.webhooks import router as webhooks_router

core_router = APIRouter()
core_router.include_router(clients_router)
core_router.include_router(client_tax_profiles_router)
core_router.include_router(client_services_router)
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
core_router.include_router(tax_router)
core_router.include_router(tax_registrations_router)
core_router.include_router(finance_settings_router)
core_router.include_router(billing_schedules_router)
core_router.include_router(receivables_router)
core_router.include_router(internal_router)

# Mount both /v1 and /api/revenue/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/revenue/v1")
