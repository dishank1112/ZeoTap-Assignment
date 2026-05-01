from fastapi import APIRouter
from app.api.routes import signals

api_router = APIRouter()
api_router.include_router(signals.router)
