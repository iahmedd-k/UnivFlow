from functools import lru_cache
from typing import List, Dict

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    # Application
    project_name: str = "Uniflow"
    app_name: str = Field(
        default="Uniflow",
        validation_alias=AliasChoices("app_name", "APP_NAME", "project_name", "PROJECT_NAME"),
    )
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    timezone: str = "Asia/Karachi"
    secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        validation_alias=AliasChoices("secret_key", "SECRET_KEY"),
    )
    encryption_key_v2: str = ""
    access_token_expire_minutes: int = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.secret_key:
            if self.is_production:
                raise ValueError("SECRET_KEY must be set in production environment")
            self.secret_key = "dev-secret-key-change-in-production"

    api_prefix: str = "/api/v1"

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://docsense:adminadmin@localhost:5432/docsense",
        validation_alias=AliasChoices("database_url", "DATABASE_URL"),
    )
    database_echo: bool = False

    # Auth / JWT
    jwt_secret_key: str = Field(
        default="change-me-in-production",
        validation_alias=AliasChoices("jwt_secret_key", "JWT_SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # CORS
    cors_origins: str | list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://docsense-one.vercel.app",
        "https://univ-flow-bt12.vercel.app",
        "https://univflow.vercel.app",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str] | None) -> list[str]:
        default_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://docsense-one.vercel.app",
            "https://univ-flow-bt12.vercel.app",
            "https://univflow.vercel.app",
        ]
        if not v:
            return default_origins
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return default_origins
            if v_str.startswith("["):
                try:
                    import json
                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            origins = [origin.strip() for origin in v_str.split(",") if origin.strip()]
            return origins if origins else default_origins
        if isinstance(v, list):
            origins = [str(origin).strip() for origin in v if str(origin).strip()]
            return origins if origins else default_origins
        return default_origins

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google"
    google_scopes: str = "https://www.googleapis.com/auth/classroom.coursework.students https://www.googleapis.com/auth/classroom.coursework.me https://www.googleapis.com/auth/classroom.coursework.me.readonly https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly https://www.googleapis.com/auth/classroom.courseworkmaterials https://www.googleapis.com/auth/classroom.announcements.readonly https://www.googleapis.com/auth/classroom.courses.readonly https://www.googleapis.com/auth/classroom.rosters.readonly https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/documents.readonly https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"

    @property
    def google_scopes_list(self) -> List[str]:
        return self.google_scopes.split()

    # AI / LLM
    ai_provider: str = "groq"
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("groq_api_key", "GROQ_API_KEY"),
    )
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_chat_model: str = Field(
        default="openai/gpt-oss-120b",
        validation_alias=AliasChoices("groq_chat_model", "GROQ_CHAT_MODEL"),
    )
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("gemini_api_key", "GEMINI_API_KEY", "Gemini_API_Key"),
    )
    study_assistant_model: str = "gemini-3.5-flash"
    pollinations_api_key: str = ""
    pollinations_base_url: str = "https://gen.pollinations.ai"
    pollinations_image_model: str = "zimage"

    # Model assignments used by the sequential CrewAI assignment workflow
    planner_agent_model: str = "gemini-3.8-flash"
    theory_agent_model: str = "gemini-3.8-flash"
    coder_agent_model: str = "llama-3.3-70b-versatile"
    reporter_agent_model: str = "gemini-3.8-flash"

    claude_enabled: bool = False

    # University Portal
    university_portal_url: str = ""
    university_portal_auth_method: str = "google"

    # Attendance
    attendance_warning_threshold: int = 75

    # Assignment checking
    assignment_check_interval_minutes: int = 30
    assignment_check_start_hour: int = 12
    assignment_check_end_hour: int = 23

    # Class reminders
    class_reminder_minutes: int = 30

    # Notifications
    notification_provider: str = "email"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    email_from: str = ""
    notification_email: str = ""

    # WhatsApp
    whatsapp_enabled: bool = False
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_webhook_verify_token: str = ""
    whatsapp_api_version: str = "v20.0"

    # Google Docs
    google_doc_template_id: str = ""

    # Playwright / Browser
    playwright_headless: bool = True
    playwright_browsers_path: str = "~/.cache/ms-playwright"
    browser_service_url: str = "http://127.0.0.1:7900"
    browser_service_token: str = ""
    browser_viewer_secret: str = ""
    browser_viewer_base_url: str = "http://localhost:7900"
    browser_cdp_host: str = "127.0.0.1"
    automatic_claude_solving: bool = False

    # Logging
    log_level: str = "INFO"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    scheduler_timezone: str = "UTC"

    # Object Storage (Cloudinary)
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    max_file_size_mb: int = 10
    local_temp_dir: str = "./tmp"

    # SendGrid
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    # Supabase (Object Storage)
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_url", "SUPABASE_URL"),
    )
    supabase_publishable_key: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_publishable_key", "SUPABASE_PUBLISHABLE_KEY"),
    )
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_secret_key", "SUPABASE_SECRET_KEY", "supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_bucket: str = "documents"
    supabase_jwks_url: str = ""

    # S3
    s3_bucket_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Clerk Auth
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""
    clerk_signing_secret: str = ""
    access_admin_email: str = "ahmedkhanofficials@gmail.com"
    access_otp_ttl_minutes: int = 10

    frontend_url: str = "http://localhost:3000"

    # Piston
    piston_base_url: str = "http://localhost:2000"
    piston_timeout_seconds: int = 30
    piston_memory_limit_mb: int = 256
    piston_cpu_limit: float = 1.0
    piston_default_packages: Dict[str, List[str]] = {}

    # Code Execution
    code_execution_timeout_seconds: int = 10
    code_execution_max_attempts: int = 3
    code_execution_max_output_bytes: int = 100000
    code_execution_max_code_bytes: int = 100000

    # Database Execution
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = ""
    mysql_user: str = ""
    mysql_password: str = ""

    mongodb_uri: str = ""
    mongodb_database: str = ""

    sqlite_execution_path: str = "./tmp/sqlite"

    # Kroki
    kroki_base_url: str = "https://kroki.io"
    kroki_timeout_seconds: int = 30

    # Diagram Generation
    diagram_max_source_bytes: int = 100000
    diagram_max_attempts: int = 2
    diagram_timeout_seconds: int = 30

    # Document upload limits
    max_file_size_mb: int = 10
    local_temp_dir: str = "./tmp"

    # Chunking defaults (FR-007)
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Retrieval
    retrieval_default_top_k: int = 10
    retrieval_max_top_k: int = 50
    fulltext_search_language: str = "english"

    # Reciprocal Rank Fusion (FR-012)
    rrf_k: int = 60

    # Cross-Encoder Reranking (FR-014)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_max_results: int = 20
    reranker_candidate_multiplier: int = 2
    min_rerank_score: float = 0.1

    # Evidence Sufficiency Grading (FR-015) — adaptive per query intent
    evidence_grading_top_k: int = 8
    evidence_grading_top_k_summarization: int = 25
    evidence_grading_top_k_qa: int = 10
    evidence_grading_top_k_comparison: int = 15
    evidence_grading_top_k_listing: int = 15
    evidence_grading_top_k_open_ended: int = 12

    # Bounded Corrective Retrieval (FR-016)
    corrective_retrieval_max_attempts: int = 2

    # Composed RAG pipeline (Flow 2 - Flow 5)
    query_analysis_max_expansion: int = 3
    query_analysis_max_sub_queries: int = 3
    answer_revision_max_attempts: int = 1

    # Embeddings (Hugging Face Inference API)
    embedding_provider: str = Field(
        default="huggingface",
        validation_alias=AliasChoices("embedding_provider", "EMBEDDING_PROVIDER"),
    )
    embedding_model: str = Field(
        default="Snowflake/snowflake-arctic-embed-m",
        validation_alias=AliasChoices("embedding_model", "EMBEDDING_MODEL"),
    )
    embedding_dimension: int = 768
    huggingface_token: str = Field(
        default="",
        validation_alias=AliasChoices("huggingface_token", "HUGGINGFACE_TOKEN", "hf_token", "HF_TOKEN"),
    )
    huggingface_inference_url: str = Field(
        default="https://router.huggingface.co/v1",
        validation_alias=AliasChoices("huggingface_inference_url", "HUGGINGFACE_INFERENCE_URL"),
    )

    # OCR (image-only PDFs). Disabled by default on memory-constrained instances.
    ocr_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("ocr_enabled", "OCR_ENABLED"),
    )
    ocr_dpi: int = Field(
        default=200,
        validation_alias=AliasChoices("ocr_dpi", "OCR_DPI"),
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def supabase_db_url(self) -> str:
        if self.database_url and self.database_url.startswith("postgresql"):
            return self.database_url
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()