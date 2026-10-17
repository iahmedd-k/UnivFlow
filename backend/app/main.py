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

extra_cors = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if getattr(settings, "cors_origins", None) else []

cors_origins = list(dict.fromkeys([
    o.rstrip("/") for o in [
        settings.frontend_url,
        "https://univ-flow-bt12.vercel.app",
        "https://univflow.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *extra_cors,
    ] if o
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin")
    headers = {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


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
        headers={"Retry-After": "5", **_cors_headers(request)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error occurred."},
        headers=_cors_headers(request),
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
    checks = {}
    
    # Database check
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"
    
    # Redis/Upstash check
    try:
        from app.core.redis import is_configured, _request
        if is_configured():
            _request("GET", "/ping")
            checks["redis"] = "healthy"
        else:
            checks["redis"] = "not_configured"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)}"
    
    # Supabase check
    try:
        from app.db.supabase_client import get_supabase_client
        supabase = get_supabase_client()
        if supabase:
            checks["supabase"] = "healthy"
        else:
            checks["supabase"] = "not_configured"
    except Exception as e:
        checks["supabase"] = f"unhealthy: {str(e)}"
    
    # S3 check
    try:
        from app.db.s3_client import get_s3_client
        s3 = get_s3_client()
        if s3:
            checks["s3"] = "healthy"
        else:
            checks["s3"] = "not_configured"
    except Exception as e:
        checks["s3"] = f"unhealthy: {str(e)}"
    
    # Piston check
    try:
        from app.integrations.piston.client import PistonClient
        import httpx
        piston = PistonClient()
        resp = httpx.get(f"{settings.piston_base_url}/health", timeout=5.0)
        if resp.status_code == 200:
            checks["piston"] = "healthy"
        else:
            checks["piston"] = f"unhealthy: HTTP {resp.status_code}"
    except Exception as e:
        checks["piston"] = f"unhealthy: {str(e)}"
    
    # Kroki check
    try:
        from app.integrations.kroki.client import KrokiClient
        kroki = KrokiClient()
        import httpx
        resp = httpx.get(f"{settings.kroki_base_url}/", timeout=5.0)
        if resp.status_code == 200:
            checks["kroki"] = "healthy"
        else:
            checks["kroki"] = f"unhealthy: HTTP {resp.status_code}"
    except Exception as e:
        checks["kroki"] = f"unhealthy: {str(e)}"
    
    all_healthy = all(v == "healthy" or v == "not_configured" for v in checks.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": settings.app_name,
        "checks": checks
    }
