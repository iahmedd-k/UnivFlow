from fastapi import APIRouter, Depends

from app.api.endpoints.agent import router as agent_router
from app.api.endpoints.assignments import router as assignments_router
from app.api.endpoints.attendance import router as attendance_router
from app.api.endpoints.auth import router as auth_router
from app.api.endpoints.classroom import router as classroom_router
from app.api.endpoints.clerk_webhook import router as clerk_router
from app.api.endpoints.dashboard import router as dashboard_router
from app.api.endpoints.documents import router as documents_router
from app.api.endpoints.integrations import router as integrations_router
from app.api.endpoints.notifications import router as notifications_router
from app.api.endpoints.portal import router as portal_router
from app.api.endpoints.rag import router as rag_router
from app.api.endpoints.timetable import router as timetable_router
from app.api.endpoints.university import router as university_router
from app.auth.access_gate import require_access_grant
from app.auth.clerk_auth import require_current_user

api_router = APIRouter()
authenticated = [Depends(require_current_user), Depends(require_access_grant)]

api_router.include_router(auth_router)
api_router.include_router(clerk_router)

for router in (
    classroom_router,
    assignments_router,
    university_router,
    attendance_router,
    dashboard_router,
    documents_router,
    notifications_router,
    agent_router,
    integrations_router,
    timetable_router,
    portal_router,
    rag_router,
):
    api_router.include_router(router, dependencies=authenticated)

