from fastapi import APIRouter, Depends
from app.auth.clerk_auth import require_current_user

from app.auth.router import router as auth_router
from app.auth.clerk_webhook import router as clerk_router
from app.classroom.router import router as classroom_router
from app.assignments.router import router as assignments_router
from app.university.router import router as university_router
from app.attendance.router import router as attendance_router
from app.dashboard.router import router as dashboard_router
from app.documents.router import router as documents_router
from app.notifications.router import router as notifications_router
from app.agent.router import router as agent_router
from app.integrations.router import router as google_integrations_router
from app.timetable.router import router as timetable_router
from app.portal.router import router as portal_router
from app.api.rag import router as rag_router


api_router = APIRouter()
authenticated = [Depends(require_current_user)]

api_router.include_router(auth_router)
api_router.include_router(clerk_router)

api_router.include_router(classroom_router, dependencies=authenticated, tags=["Classroom"])
api_router.include_router(assignments_router, dependencies=authenticated, tags=["Assignments"])
api_router.include_router(university_router, dependencies=authenticated, tags=["University"])
api_router.include_router(attendance_router, dependencies=authenticated, tags=["Attendance"])
api_router.include_router(dashboard_router, dependencies=authenticated, tags=["Dashboard"])
api_router.include_router(documents_router, dependencies=authenticated, tags=["Documents"])
api_router.include_router(notifications_router, dependencies=authenticated, tags=["Notifications"])
api_router.include_router(agent_router, dependencies=authenticated, tags=["Agent"])
api_router.include_router(google_integrations_router, dependencies=authenticated)
api_router.include_router(timetable_router, dependencies=authenticated)
api_router.include_router(portal_router, dependencies=authenticated)
api_router.include_router(rag_router, dependencies=authenticated, tags=["RAG"])
