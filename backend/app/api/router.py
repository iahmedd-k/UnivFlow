from fastapi import APIRouter

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

api_router.include_router(auth_router)
api_router.include_router(clerk_router)

api_router.include_router(classroom_router, tags=["Classroom"])
api_router.include_router(assignments_router, tags=["Assignments"])
api_router.include_router(university_router, tags=["University"])
api_router.include_router(attendance_router, tags=["Attendance"])
api_router.include_router(dashboard_router, tags=["Dashboard"])
api_router.include_router(documents_router, tags=["Documents"])
api_router.include_router(notifications_router, tags=["Notifications"])
api_router.include_router(agent_router, tags=["Agent"])
api_router.include_router(google_integrations_router)
api_router.include_router(timetable_router)
api_router.include_router(portal_router)
api_router.include_router(rag_router, tags=["RAG"])
