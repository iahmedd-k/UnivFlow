from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.usage import UsageResponse
from app.services.usage_service import UsageService

router = APIRouter(prefix="/usage", tags=["usage"])


def get_usage_service(db: Session = Depends(get_db)) -> UsageService:
    return UsageService(db)


@router.get(
    "",
    response_model=ApiResponse[UsageResponse],
    summary="Return the authenticated user's usage and quota information",
)
def get_usage(
    current_user: User = Depends(get_current_user),
    usage_service: UsageService = Depends(get_usage_service),
):
    result = usage_service.get_usage(current_user.id)
    return ApiResponse(success=True, data=result, message="Usage information retrieved.")
