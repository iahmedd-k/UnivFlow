from fastapi import APIRouter

from app.core.logging import get_memory_rss_mb

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health_check():
    return {"status": "ok"}


@router.get("/healthz", summary="Health check with memory usage")
def health_check_z():
    return {"status": "ok", "memory_rss_mb": round(get_memory_rss_mb(), 1)}