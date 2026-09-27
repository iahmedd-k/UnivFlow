from app.services.storage import storage_service, get_storage_service, SupabaseStorageService
from app.services.email import send_email, send_template_email, get_sendgrid_client
from app.services.classroom_sync import ClassroomSyncService, get_classroom_service
from app.services.google_docs import GoogleDocsService, get_google_docs_service
from app.services.ai_solution import generate_solution, validate_solution

__all__ = [
    "storage_service",
    "get_storage_service",
    "SupabaseStorageService",
    "send_email",
    "send_template_email",
    "get_sendgrid_client",
    "ClassroomSyncService",
    "get_classroom_service",
    "GoogleDocsService",
    "get_google_docs_service",
    "generate_solution",
    "validate_solution",
]