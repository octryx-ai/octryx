from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.comms.notification import (
    NotificationLogResponse,
    NotificationSubscriptionRequest,
    NotificationSubscriptionResponse,
    NotificationTemplateRequest,
    NotificationTemplateResponse,
)
from ....services.access_control import require_existing_workspace
from ....services.auth import get_current_user
from ....services.auth.admin_principal import get_current_admin_user
from ....services.notification_delivery import (
    delete_notification_subscription,
    delete_notification_template,
    list_notification_log,
    list_notification_subscriptions,
    list_notification_templates,
    require_admin_user,
    send_test_delivery,
    upsert_notification_subscription,
    upsert_notification_template,
)

router = APIRouter(prefix="/admin", tags=["admin-notifications"])


@router.get("/notification-templates", response_model=list[NotificationTemplateResponse])
async def get_notification_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_notification_templates(db)


@router.post("/notification-templates", response_model=NotificationTemplateResponse)
async def post_notification_template(
    body: NotificationTemplateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, current_user.id, body.project_id)
    return await upsert_notification_template(db, current_user=current_user, payload=body.model_dump())


@router.put("/notification-templates/{template_id}", response_model=NotificationTemplateResponse)
async def put_notification_template(
    template_id: str,
    body: NotificationTemplateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, current_user.id, body.project_id)
    return await upsert_notification_template(
        db,
        current_user=current_user,
        payload=body.model_dump(),
        template_id=template_id,
    )


@router.delete("/notification-templates/{template_id}")
async def remove_notification_template(
    template_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await delete_notification_template(db, current_user=current_user, template_id=template_id)


@router.get("/notification-subscriptions", response_model=list[NotificationSubscriptionResponse])
async def get_admin_notification_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_notification_subscriptions(db, current_user=current_user, admin_scope=True)


@router.post("/notification-subscriptions", response_model=NotificationSubscriptionResponse)
async def post_admin_notification_subscription(
    body: NotificationSubscriptionRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, current_user.id, body.project_id)
    return await upsert_notification_subscription(
        db,
        current_user=current_user,
        payload=body.model_dump(),
        admin_scope=True,
    )


@router.put("/notification-subscriptions/{subscription_id}", response_model=NotificationSubscriptionResponse)
async def put_admin_notification_subscription(
    subscription_id: str,
    body: NotificationSubscriptionRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, current_user.id, body.project_id)
    return await upsert_notification_subscription(
        db,
        current_user=current_user,
        payload=body.model_dump(),
        subscription_id=subscription_id,
        admin_scope=True,
    )


@router.delete("/notification-subscriptions/{subscription_id}")
async def remove_admin_notification_subscription(
    subscription_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await delete_notification_subscription(
        db,
        current_user=current_user,
        subscription_id=subscription_id,
        admin_scope=True,
    )


@router.post("/notification-subscriptions/{subscription_id}/test", response_model=NotificationLogResponse)
async def post_admin_notification_subscription_test(
    subscription_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue one test message on the subscription (the delivery log shows whether it went out)."""
    return await send_test_delivery(db, current_user=current_user, subscription_id=subscription_id,
                                    admin_scope=True)


@router.get("/notification-log", response_model=list[NotificationLogResponse])
async def get_admin_notification_log(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_notification_log(
        db,
        current_user=current_user,
        admin_scope=True,
        status_filter=status_filter,
        limit=limit,
    )
