from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.comms.notification import (
    NotificationLogResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationResponse,
    NotificationSubscriptionRequest,
    NotificationSubscriptionResponse,
)
from ....services.access_control import require_project_access
from ....services.auth import get_current_user
from ....services.notification_delivery import (
    delete_notification_subscription,
    list_notification_log,
    list_notification_subscriptions,
    send_test_delivery,
    upsert_notification_subscription,
)
from ....services.team_notification import (
    get_notification_preferences,
    list_notifications,
    mark_notification_read,
    update_notification_preferences,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_notifications(db, current_user=current_user, unread_only=unread_only, limit=limit)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def read_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await mark_notification_read(db, notification_id=notification_id, current_user=current_user)


@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_notification_preferences(db, current_user)


@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def put_preferences(
    body: NotificationPreferenceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ....services.attention.quiet_hours import QuietHoursError

    try:
        return await update_notification_preferences(
            db,
            current_user=current_user,
            in_app_enabled=body.in_app_enabled,
            email_enabled=body.email_enabled,
            slack_enabled=body.slack_enabled,
            teams_enabled=body.teams_enabled,
            quiet_hours=body.quiet_hours,
        )
    except QuietHoursError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_quiet_hours", "message": str(exc)}) from exc


@router.get("/subscriptions", response_model=list[NotificationSubscriptionResponse])
async def get_notification_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_notification_subscriptions(db, current_user=current_user, admin_scope=False)


@router.post("/subscriptions", response_model=NotificationSubscriptionResponse)
async def post_notification_subscription(
    body: NotificationSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    return await upsert_notification_subscription(
        db,
        current_user=current_user,
        payload=body.model_dump(),
        admin_scope=False,
    )


@router.post("/subscriptions/{subscription_id}/test", response_model=NotificationLogResponse)
async def post_notification_subscription_test(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue one test message on the person's own subscription."""
    return await send_test_delivery(db, current_user=current_user, subscription_id=subscription_id)


@router.put("/subscriptions/{subscription_id}", response_model=NotificationSubscriptionResponse)
async def put_notification_subscription(
    subscription_id: str,
    body: NotificationSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    return await upsert_notification_subscription(
        db,
        current_user=current_user,
        payload=body.model_dump(),
        subscription_id=subscription_id,
        admin_scope=False,
    )


@router.delete("/subscriptions/{subscription_id}")
async def remove_notification_subscription(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await delete_notification_subscription(
        db,
        current_user=current_user,
        subscription_id=subscription_id,
        admin_scope=False,
    )


@router.get("/delivery-log", response_model=list[NotificationLogResponse])
async def get_notification_delivery_log(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_notification_log(
        db,
        current_user=current_user,
        admin_scope=False,
        limit=limit,
    )
