from fastapi import APIRouter

from app.v1.api.endpoints import execution, diagram

api_router = APIRouter()

api_router.include_router(execution.router)
api_router.include_router(diagram.router)