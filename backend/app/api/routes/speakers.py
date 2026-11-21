"""API endpoints for speaker enrollment and management.

Allows registering speaker voice profiles so the meeting assistant can
identify who said what during calls.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...schemas.core.workspace_ref import WorkspaceId
from ...services.access_control import require_existing_workspace
from ...services.auth.admin_principal import get_current_admin_user
from ...services.error_facts import error_text
from ...services.speaker.diarization import (
    _speaker_profiles,
    enroll_speaker,
    get_enrolled_speakers,
    set_hf_token,
)

# Admin-only: voice profiles and the process-wide HuggingFace token are platform configuration.
router = APIRouter(
    prefix="/api/v1/speakers", tags=["speakers"], dependencies=[Depends(get_current_admin_user)]
)
logger = logging.getLogger(__name__)


@router.post("/enroll")
async def enroll_speaker_endpoint(
    name: str = Form(..., description="Speaker name (e.g., 'Alice', 'Bob')"),
    project_id: WorkspaceId = Form(..., description="Project ID this speaker belongs to"),
    audio: UploadFile = File(..., description="WAV audio of the speaker talking (~10s recommended)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enroll a speaker by uploading a voice sample.

    Upload a ~10 second WAV recording of the speaker talking normally.
    The system will extract a voice fingerprint that is used to identify
    this person during meetings.
    """
    await require_existing_workspace(db, project_id)
    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Audio file too small. Need at least a few seconds of speech.")

    try:
        profile = enroll_speaker(name=name, audio_bytes=audio_bytes, project_id=project_id)
        return {
            "status": "enrolled",
            "speaker_name": profile.name,
            "project_id": profile.project_id,
            "enrolled_at": profile.enrolled_at,
            "embedding_dim": len(profile.embedding),
        }
    except Exception as exc:
        logger.exception("Speaker enrollment failed for '%s'", name)
        raise HTTPException(
            status_code=500,
            detail=f"Enrollment failed. {error_text('speaker_enrollment_failed', exc)}",
        ) from exc


@router.get("/list/{project_id}")
async def list_speakers(project_id: str) -> dict:
    """List all enrolled speakers for a project."""
    profiles = get_enrolled_speakers(project_id)
    return {
        "project_id": project_id,
        "speakers": [
            {
                "name": p.name,
                "enrolled_at": p.enrolled_at,
            }
            for p in profiles
        ],
        "count": len(profiles),
    }


@router.delete("/remove")
async def remove_speaker(
    name: str = Form(...),
    project_id: WorkspaceId = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove an enrolled speaker."""
    await require_existing_workspace(db, project_id)
    if project_id in _speaker_profiles:
        before = len(_speaker_profiles[project_id])
        _speaker_profiles[project_id] = [p for p in _speaker_profiles[project_id] if p.name != name]
        after = len(_speaker_profiles[project_id])
        if before > after:
            return {"status": "removed", "speaker_name": name}
    raise HTTPException(status_code=404, detail=f"Speaker '{name}' not found in project")


@router.post("/set-hf-token")
async def set_huggingface_token(token: str = Form(...)) -> dict:
    """Set the HuggingFace token for pyannote model access.

    Required for first-time setup. The pyannote models need an accepted
    license on huggingface.co.
    """
    set_hf_token(token)
    return {"status": "token_set"}
