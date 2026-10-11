from fastapi import APIRouter

from app.api.router import api_router as feature_api_router
from app.v1.api.endpoints import execution, diagram

api_router = APIRouter()

# Register feature endpoints under the same versioned prefix used by the web client.
api_router.include_router(feature_api_router)

# Version-specific endpoints live in app.v1.api.endpoints.
api_router.include_router(execution.router)
api_router.include_router(diagram.router)
