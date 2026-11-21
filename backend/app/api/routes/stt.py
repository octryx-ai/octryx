"""STT API for server-side audio transcription.

Both routes require an active user; a Workspace's STT configuration is used only for a member of
that Workspace (or an admin), so ``project_id`` never selects another team's provider; an unknown or foreign one is
404 ``project_not_found`` before any audio is sent (``require_visible_workspace``).
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import AuditLog, User
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user

router = APIRouter(prefix="/api/v1/stt", tags=["stt"])


def _record_stt_resolution_audit(db: AsyncSession, *, user_id: str, action: str, details: dict) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type="speech_stt",
            resource_id=details.get("selected_provider") or "none",
            details=details,
        )
    )


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    project_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Transcribe uploaded audio file using the configured STT provider."""
    from ...services.stt import resolve_stt_service

    await require_visible_workspace(db, current_user.id, project_id)
    resolution = await resolve_stt_service(db, project_id=project_id)
    svc = resolution.service
    if not svc:
        _record_stt_resolution_audit(
            db,
            user_id=current_user.id,
            action="speech.stt.provider_unavailable",
            details=resolution.to_audit_dict(),
        )
        await db.commit()
        raise HTTPException(503, "STT service not configured. Set stt/whisper_base_url or stt/openai_api_key.")
    if resolution.fallback_used:
        _record_stt_resolution_audit(
            db,
            user_id=current_user.id,
            action="speech.stt.fallback_selected",
            details=resolution.to_audit_dict(),
        )
        await db.commit()
    content = await audio.read()
    if not content:
        raise HTTPException(400, "Empty audio file")
    try:
        text = await svc.transcribe(content, filename=audio.filename or "audio.webm")
    except Exception as exc:
        from ...services.redaction_policy import redact_secret_text

        safe_error = redact_secret_text(exc, max_chars=500)
        details = {
            **resolution.to_audit_dict(),
            "error_type": type(exc).__name__,
            "error": safe_error,
        }
        _record_stt_resolution_audit(
            db,
            user_id=current_user.id,
            action="speech.stt.transcription_failed",
            details=details,
        )
        await db.commit()
        raise HTTPException(502, f"STT provider error: {safe_error}")
    return {"text": text}


@router.get("/status")
async def stt_status(
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if STT is available (optionally for a specific project)."""
    from ...services.stt import resolve_stt_service

    await require_visible_workspace(db, current_user.id, project_id)
    resolution = await resolve_stt_service(db, project_id=project_id)
    svc = resolution.service
    return {
        "available": svc is not None,
        "provider": getattr(svc, "provider_name", None) if svc else None,
        "fallback_allowed": resolution.fallback_allowed,
        "fallback_used": resolution.fallback_used,
        "resolution": resolution.to_audit_dict(),
    }
