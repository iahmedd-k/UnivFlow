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
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import logger
from app.db.database import init_db, get_db
from app.db.supabase_client import init_supabase
from app.db.s3_client import init_s3
from app.v1.api.router import api_router as v1_api_router
# Uniflow FastAPI Main Application - Updated
from app.auth.router import google_callback


from app.services.scheduler import start_scheduler, shutdown_scheduler


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
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler start failed: {e}")
    yield
    shutdown_scheduler()
    logger.info("Shutting down Uniflow...")


app = FastAPI(
    title=settings.app_name,
    description="Uniflow - Unified Academic Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

cors_origins = [
    settings.frontend_url,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
cors_origins = list(set([o for o in cors_origins if o]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_unavailable_handler(request: Request, exc: OperationalError):
    logger.error(
        "Database operation failed on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is temporarily unavailable. Please try again shortly."},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error occurred."},
        headers={
            "Access-Control-Allow-Origin": request.headers.get("origin") or "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


# API routes under /api/v1
app.include_router(v1_api_router, prefix="/api/v1")


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
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "service": settings.app_name, "database": "connected"}
