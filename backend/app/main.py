import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import logger
from app.db.database import init_db, get_db
from app.db.supabase_client import init_supabase
from app.db.s3_client import init_s3
from app.api import api_router
# Uniflow FastAPI Main Application - Updated
from app.auth.router import google_callback


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Uniflow...")
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    try:
        init_supabase()
        logger.info("Supabase client initialized")
    except Exception as e:
        logger.warning(f"Supabase initialization failed: {e}")
    try:
        init_s3()
        logger.info("S3 client initialized")
    except Exception as e:
        logger.warning(f"S3 initialization failed: {e}")
    yield
    logger.info("Shutting down Uniflow...")


app = FastAPI(
    title=settings.app_name,
    description="Uniflow - Unified Academic Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = [
    settings.frontend_url,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
# Remove duplicates
cors_origins = list(set([o for o in cors_origins if o]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes under /api/v1
app.include_router(api_router, prefix="/api/v1")


# Direct alias for Google OAuth callback matching standard redirect URIs
@app.get("/auth/google/callback", include_in_schema=False)
def root_google_callback(request: Request, db: Session = Depends(get_db)):
    return google_callback(request=request, db=db)


@app.get("/")
def root():
    return {
        "message": "Welcome to Uniflow API",
        "version": "1.0.0",
        "docs": "/docs",
        "api": "/api/v1"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.app_name}
