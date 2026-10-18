from fastapi import APIRouter

from app.api.router import api_router as feature_api_router

api_router = APIRouter()

# Feature routers apply their own authentication and private access dependencies.
api_router.include_router(feature_api_router)

# The app uses Claude for assignment work. Standalone manual execution and
# diagram-generation endpoints are intentionally not exposed.
