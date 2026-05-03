from fastapi import APIRouter

from app.api.routes import incidents, rca, signals

api_router = APIRouter()
api_router.include_router(signals.router)
api_router.include_router(incidents.router)
api_router.include_router(rca.router)
