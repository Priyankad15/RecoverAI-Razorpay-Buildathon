"""
RecoverAI API entrypoint.

Phase 1: app wiring, CORS, health-check.
Phase 6: dashboard/payments/recovery/audit routers wired in - the API
surface a merchant-facing frontend actually talks to.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import router as audit_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.payments import router as payments_router
from app.api.razorpay_webhook import router as razorpay_webhook_router
from app.api.recovery import router as recovery_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(payments_router)
app.include_router(recovery_router)
app.include_router(audit_router)
app.include_router(razorpay_webhook_router)
