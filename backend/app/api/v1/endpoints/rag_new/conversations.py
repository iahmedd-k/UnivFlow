from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import AppException
from app.db.session import get_db
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_conversation_service(
    db: Session = Depends(get_db),
) -> ConversationService:
    return ConversationService(db)


@router.post(
    "",
    response_model=ApiResponse[ConversationResponse],
    status_code=201,
    summary="Create a new conversation",
)
def create_conversation(
    request: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    result = service.create_conversation(
        user_id=current_user.id,
        title=request.title,
        document_ids=request.document_ids,
    )
    return ApiResponse(success=True, data=result, message="Conversation created")


@router.get(
    "",
    response_model=ApiResponse[ConversationListResponse],
    summary="List user conversations",
)
def list_conversations(
    current_user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    result = service.list_conversations(
        user_id=current_user.id,
        offset=offset,
        limit=limit,
    )
    return ApiResponse(success=True, data=result)


@router.get(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationDetailResponse],
    summary="Get conversation with messages",
)
def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    result = service.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return ApiResponse(success=True, data=result)


@router.patch(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationResponse],
    summary="Update conversation title",
)
def update_conversation(
    conversation_id: int,
    request: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    result = service.update_conversation_title(
        conversation_id=conversation_id,
        user_id=current_user.id,
        title=request.title,
    )
    return ApiResponse(success=True, data=result, message="Conversation updated")


@router.delete(
    "/{conversation_id}",
    status_code=204,
    summary="Delete a conversation",
)
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    service.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return Response(status_code=204)
