from fastapi import APIRouter

from app.api.v1 import auth, batches, health, reports

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(batches.router)
api_router.include_router(reports.router)
