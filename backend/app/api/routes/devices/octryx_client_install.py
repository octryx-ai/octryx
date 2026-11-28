"""Public octryx-claude install endpoints: installer scripts, package and version."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from ....services.knowledge.episodes.policy import public_origin
from ....services.octryx_client.artifact import ClientArtifactError, current_artifact
from ....services.octryx_client.installers import (
    INSTALL_PS1,
    INSTALL_SH,
    InstallerRenderError,
    install_commands,
    installer_template,
    render,
    valid_base_url,
    valid_workspace,
)

router = APIRouter(prefix="/octryx-claude", tags=["octryx-claude-install"])

SCRIPT_CACHE_CONTROL = "no-cache"
PACKAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"
WHEEL_MEDIA_TYPE = "application/octet-stream"
_REFUSAL_STATUS = {"workspace_invalid": 422, "installer_unknown": 404}


def _base_url(request: Request) -> str:
    return public_origin() or str(request.base_url).rstrip("/")


def _refusal(code: str) -> JSONResponse:
    state = "denied" if code in _REFUSAL_STATUS else "needs_configuration"
    return JSONResponse({"state": state, "reason": code}, status_code=_REFUSAL_STATUS.get(code, 503))


def _script(request: Request, name: str, workspace: str) -> Response:
    try:
        body = render(installer_template(name), base_url=_base_url(request), workspace=workspace)
    except (InstallerRenderError, ClientArtifactError) as exc:
        return _refusal(exc.code)
    return PlainTextResponse(body, headers={"Cache-Control": SCRIPT_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"})


@router.get("/install.sh")
async def octryx_install_sh(request: Request, workspace: str = "") -> Response:
    return _script(request, INSTALL_SH, workspace)


@router.get("/install.ps1")
async def octryx_install_ps1(request: Request, workspace: str = "") -> Response:
    return _script(request, INSTALL_PS1, workspace)


@router.get("/version")
async def octryx_client_version(request: Request, workspace: str = "") -> Response:
    base_url = _base_url(request)
    if not valid_base_url(base_url):
        return _refusal("base_url_unusable")
    if workspace and not valid_workspace(workspace):
        return _refusal("workspace_invalid")
    try:
        artifact = current_artifact()
    except ClientArtifactError as exc:
        return _refusal(exc.code)
    return JSONResponse(
        {
            "client": "octryx-claude",
            "version": artifact.version,
            "filename": artifact.filename,
            "sha256": artifact.sha256,
            "package_url": f"{base_url}/octryx-claude/package/{artifact.version}",
            "requires_python": artifact.requires_python,
            "install": install_commands(base_url, workspace),
        },
        headers={"Cache-Control": SCRIPT_CACHE_CONTROL},
    )


@router.get("/package/{version}")
async def octryx_client_package(version: str) -> Response:
    try:
        artifact = current_artifact()
    except ClientArtifactError as exc:
        return _refusal(exc.code)
    if version != artifact.version:
        return JSONResponse({"state": "denied", "reason": "package_version_not_served"}, status_code=404)
    return Response(
        artifact.content,
        media_type=WHEEL_MEDIA_TYPE,
        headers={
            "Cache-Control": PACKAGE_CACHE_CONTROL,
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Checksum-Sha256": artifact.sha256,
        },
    )
