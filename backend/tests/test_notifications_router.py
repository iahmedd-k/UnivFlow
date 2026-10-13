from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

from app.notifications.router import (
    CreateNotificationForMeRequest,
    create_notification_for_me,
)


def test_create_notification_for_me_accepts_request_body():
    request = CreateNotificationForMeRequest(
        notification_type="test",
        subject="Test notification",
        payload="Body payload",
        external_id="external-1",
        idempotency_key="idempotency-1",
    )
    background_tasks = BackgroundTasks()
    db = MagicMock()
    created = {"notification_id": 42, "status": "PENDING"}

    with patch(
        "app.notifications.router._get_user_notification_email",
        return_value="student@example.com",
    ), patch(
        "app.notifications.router.create_notification",
        return_value=created,
    ) as create_notification:
        result = create_notification_for_me(
            request=request,
            background_tasks=background_tasks,
            db=db,
            clerk_user={"id": "user-1"},
        )

    assert result == created
    create_notification.assert_called_once_with(
        notification_type="test",
        background_tasks=background_tasks,
        recipient="student@example.com",
        subject="Test notification",
        payload="Body payload",
        external_id="external-1",
        idempotency_key="idempotency-1",
        db=db,
        clerk_user={"id": "user-1"},
    )
