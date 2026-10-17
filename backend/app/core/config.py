from pydantic_settings import BaseSettings
from typing import Optional, List, Dict
from functools import lru_cache
import secrets


class Settings(BaseSettings):
    app_name: str = "Uniflow"
    environment: str = "development"
    debug: bool = False
    timezone: str = "Asia/Karachi"
    secret_key: str = ""
    encryption_key_v2: str = ""
    access_token_expire_minutes: int = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.secret_key:
            if self.is_production:
                raise ValueError("SECRET_KEY must be set in production environment")
            self.secret_key = secrets.token_urlsafe(32)

    database_url: str = ""
    database_echo: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google"
    google_scopes: str = "https://www.googleapis.com/auth/classroom.coursework.students https://www.googleapis.com/auth/classroom.coursework.me.readonly https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly https://www.googleapis.com/auth/classroom.courseworkmaterials https://www.googleapis.com/auth/classroom.announcements.readonly https://www.googleapis.com/auth/classroom.courses.readonly https://www.googleapis.com/auth/classroom.rosters.readonly https://www.googleapis.com/auth/documents.readonly https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"

    ai_provider: str = "groq"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_chat_model: str = "openai/gpt-oss-120b"
    gemini_api_key: str = ""
    pollinations_api_key: str = ""
    pollinations_base_url: str = "https://gen.pollinations.ai"
    pollinations_image_model: str = "zimage"

    # Model assignments used by the sequential CrewAI assignment workflow.
    planner_agent_model: str = "llama-3.3-70b-versatile"
    theory_agent_model: str = "gemini-2.0-flash"
    coder_agent_model: str = "llama-3.3-70b-versatile"
    reporter_agent_model: str = "gemini-2.0-flash"

    claude_enabled: bool = False

    university_portal_url: str = ""
    university_portal_auth_method: str = "google"

    attendance_warning_threshold: int = 75

    assignment_check_interval_minutes: int = 30
    assignment_check_start_hour: int = 12
    assignment_check_end_hour: int = 23

    class_reminder_minutes: int = 30

    notification_provider: str = "email"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    email_from: str = ""
    notification_email: str = ""

    whatsapp_enabled: bool = False
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_webhook_verify_token: str = ""
    whatsapp_api_version: str = "v20.0"

    google_doc_template_id: str = ""

    playwright_headless: bool = True
    playwright_browsers_path: str = "~/.cache/ms-playwright"
    browser_service_url: str = "http://127.0.0.1:7900"
    browser_service_token: str = ""
    browser_viewer_secret: str = ""
    browser_viewer_base_url: str = "http://localhost:7900"
    browser_cdp_host: str = "127.0.0.1"
    automatic_claude_solving: bool = False

    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    scheduler_timezone: str = "UTC"

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    max_file_size_mb: int = 10
    local_temp_dir: str = "./tmp"

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_jwks_url: str = ""

    s3_bucket_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Clerk Auth
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""
    clerk_signing_secret: str = ""

    frontend_url: str = "http://localhost:5173"
    cors_origins: str = ""

    # Piston Configuration
    piston_base_url: str = "http://localhost:2000"
    piston_timeout_seconds: int = 30
    piston_memory_limit_mb: int = 256
    piston_cpu_limit: float = 1.0
    piston_default_packages: Dict[str, List[str]] = {}

    # Code Execution Limits
    code_execution_timeout_seconds: int = 10
    code_execution_max_attempts: int = 3
    code_execution_max_output_bytes: int = 100000
    code_execution_max_code_bytes: int = 100000

    # Database Execution Configuration
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = ""
    mysql_user: str = ""
    mysql_password: str = ""

    mongodb_uri: str = ""
    mongodb_database: str = ""

    sqlite_execution_path: str = "./tmp/sqlite"

    # Kroki Configuration
    kroki_base_url: str = "https://kroki.io"
    kroki_timeout_seconds: int = 30

    # Diagram Generation Limits
    diagram_max_source_bytes: int = 100000
    diagram_max_attempts: int = 2
    diagram_timeout_seconds: int = 30

    @property
    def google_scopes_list(self) -> List[str]:
        return self.google_scopes.split()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def supabase_db_url(self) -> str:
        if self.database_url and self.database_url.startswith("postgresql"):
            return self.database_url
        return ""

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
