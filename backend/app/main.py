from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.logging import logger
from app.db.database import init_db
from app.db.supabase_client import init_supabase
from app.db.s3_client import init_s3
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Uniflow...")
    init_db()
    logger.info("Database initialized")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"message": "Welcome to Uniflow API", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": settings.app_name}