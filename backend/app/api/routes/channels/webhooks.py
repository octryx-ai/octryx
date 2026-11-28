"""Webhook management and trigger endpoints."""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.integration.webhook import Webhook, WebhookEvent
from ....schemas.comms.webhook import WebhookCreate, WebhookEventResponse, WebhookResponse, WebhookSecretResponse
from ....services.access_control import require_existing_workspace
from ....services.admin.connector import admin_webhook_service
from ....services.auth import get_current_user
from ....services.auth.admin_principal import get_current_admin_user
from ....services.data_access.machine_principal import authenticating_owner
from ....services.inbound_alerts.call_guard import allow_call
from ....services.inbound_alerts.trigger import receive_alert, verify_signature
from ....services.project.private_workspace import hidden_private_ids

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])



def _response(webhook: Webhook, secret: str | None, *,
              model: type[WebhookResponse] = WebhookResponse) -> WebhookResponse:
    return model(
        id=webhook.id,
        project_id=webhook.project_id,
        owner_id=webhook.owner_id,
        name=webhook.name,
        description=webhook.description,
        source_type=webhook.source_type,
        task_id=webhook.task_id,
        alert_filter=webhook.alert_filter or "critical_warning",
        group_window_minutes=int(webhook.group_window_minutes or 0),
        rate_limit_per_hour=int(webhook.rate_limit_per_hour or 20),
        accept_untimestamped=bool(webhook.accept_untimestamped),
        # WebhookResponse masks it; only a create or a rotate answers with the raw value, once.
        secret=secret or "",
        is_active=webhook.is_active,
        created_at=webhook.created_at.isoformat(),
    )


async def _owned(db: AsyncSession, webhook_id: str, user_id: str) -> Webhook:
    webhook = (await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.owner_id == user_id))).scalar_one_or_none()
    if webhook is None or webhook.project_id in await hidden_private_ids(db, user_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all webhooks the current user owns, optionally filtered by project."""
    hidden = await hidden_private_ids(db, current_user.id)
    q = select(Webhook).where(Webhook.owner_id == current_user.id, Webhook.project_id.not_in(hidden))
    if project_id:
        q = q.where(Webhook.project_id == project_id)
    result = await db.execute(q.order_by(Webhook.created_at.desc()))
    return [_response(w, None) for w in result.scalars().all()]


@router.post("", response_model=WebhookSecretResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a webhook that starts an Action (same validation as the admin panel; Action of the same Workspace)."""
    await require_existing_workspace(db, current_user.id, body.project_id)
    created = await admin_webhook_service.create_webhook(
        db, user_id=current_user.id, payload=body.model_dump(exclude_none=True)
    )
    webhook = await db.get(Webhook, created["id"])
    return _response(webhook, created["secret"], model=WebhookSecretResponse)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookSecretResponse)
async def rotate_webhook_secret(
    webhook_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new secret and return it once (the old one stops working at once); audited."""
    rotated = await admin_webhook_service.rotate_webhook_secret(db, webhook_id=webhook_id, user_id=current_user.id)
    webhook = await db.get(Webhook, webhook_id)
    return _response(webhook, rotated["secret"], model=WebhookSecretResponse)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhook = await _owned(db, webhook_id, current_user.id)
    await db.delete(webhook)
    await db.commit()


@router.get("/{webhook_id}/events", response_model=list[WebhookEventResponse])
async def list_webhook_events(
    webhook_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent events received by this webhook."""
    await _owned(db, webhook_id, current_user.id)

    result = await db.execute(
        select(WebhookEvent)
        .where(WebhookEvent.webhook_id == webhook_id)
        .order_by(WebhookEvent.received_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        WebhookEventResponse(
            id=e.id,
            webhook_id=e.webhook_id,
            session_id=e.session_id,
            status=e.status,
            parsed_message=e.parsed_message,
            error=e.error,
            received_at=e.received_at.isoformat(),
            processed_at=e.processed_at.isoformat() if e.processed_at else None,
        )
        for e in events
    ]


# Public trigger endpoint: no JWT, authenticated by the webhook's secret.


@router.post("/{webhook_id}/trigger", status_code=202)
async def trigger_webhook(webhook_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Receive an alert and start the webhook's Action (or record why it did not start)."""
    client = request.client.host if request.client else "unknown"
    if not allow_call(webhook_id, client):
        raise HTTPException(status_code=429, detail="Too many calls; slow down")
    body, headers = await request.body(), dict(request.headers)
    async with authenticating_owner(db, Webhook, webhook_id, owner_column="owner_id") as owner:
        webhook = (await db.execute(select(Webhook).where(Webhook.id == webhook_id))).scalar_one_or_none()
        if not webhook:
            raise _webhook_not_found()
        try:
            signature = await verify_signature(db, webhook, body, headers)
        except HTTPException:
            if owner.private:
                raise _webhook_not_found() from None
            raise
    return await receive_alert(db, webhook=webhook, body=body, headers=headers, signature=signature)


def _webhook_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Webhook not found")
