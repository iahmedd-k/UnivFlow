from pydantic_settings import BaseSettings
from typing import Optional, List
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "Uniflow"
    environment: str = "development"
    timezone: str = "Asia/Karachi"
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 30

    database_url: str = ""
    database_echo: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google"
    google_scopes: str = "https://www.googleapis.com/auth/classroom.coursework.students https://www.googleapis.com/auth/classroom.coursework.me.readonly https://www.googleapis.com/auth/classroom.announcements.readonly https://www.googleapis.com/auth/classroom.courses.readonly https://www.googleapis.com/auth/classroom.rosters.readonly https://www.googleapis.com/auth/documents.readonly https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"

    ai_provider: str = "groq"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_chat_model: str = "openai/gpt-oss-120b"

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

    playwright_headless: bool = False
    playwright_browsers_path: str = "~/.cache/ms-playwright"

    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"
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

    @property
    def google_scopes_list(self) -> List[str]:
        return self.google_scopes.split()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def supabase_db_url(self) -> str:
        # A Supabase API key is not the Postgres password. Never synthesize a
        # database connection string from SUPABASE_URL or SUPABASE_SECRET_KEY.
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
