from fastapi import APIRouter, Depends

from app.api.router import api_router as feature_api_router
from app.auth.clerk_auth import require_current_user
from app.v1.api.endpoints import execution, diagram

api_router = APIRouter()

# Register feature endpoints under the same versioned prefix used by the web client.
authenticated = [Depends(require_current_user)]
# Feature routers apply their own auth dependencies. Do not apply auth here:
# the Google OAuth callback must accept the redirect without a Clerk bearer token.
api_router.include_router(feature_api_router)

# Version-specific endpoints live in app.v1.api.endpoints.
api_router.include_router(execution.router, dependencies=authenticated)
api_router.include_router(diagram.router, dependencies=authenticated)
