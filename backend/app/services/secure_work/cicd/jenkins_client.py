from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

import httpx


class JenkinsClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JenkinsRuntimeConfig:
    base_url: str
    credential_ref: str | None = None
    timeout_seconds: float = 20.0
    username: str | None = None
    token: str | None = field(default=None, repr=False)


class JenkinsClient:
    def __init__(
        self,
        config: JenkinsRuntimeConfig,
        *,
        client_factory: Any | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory or httpx.AsyncClient
        self._base_url = config.base_url.rstrip("/")

    async def test_connection(self, *, limit: int = 10) -> dict[str, Any]:
        jobs = await self.list_jobs(limit=limit)
        return {
            "status": "ok",
            "job_count": len(jobs),
            "credential_ref": self.config.credential_ref,
            "jobs": jobs[:limit],
        }

    async def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._get_json(
            "/api/json",
            params={"tree": "jobs[name,fullName,url,color,jobs[name,fullName,url,color]]"},
        )
        return _flatten_jobs(data.get("jobs") or [])[: max(1, min(limit, 500))]

    async def list_builds(self, job_name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        path = f"{_job_path(job_name)}/api/json"
        tree = "builds[number,url,result,building,timestamp,duration,actions[lastBuiltRevision[SHA1]]]"
        data = await self._get_json(path, params={"tree": tree})
        return [_normalize_build(job_name, item) for item in (data.get("builds") or [])[: max(1, min(limit, 100))]]

    async def get_build_status(self, job_name: str, build_number: str | int) -> dict[str, Any]:
        data = await self._get_json(f"{_job_path(job_name)}/{quote(str(build_number), safe='')}/api/json")
        return _normalize_build(job_name, data)

    async def queued_build_number(self, queue_url: str) -> str | None:
        """The build a queue item (``trigger_build``'s ``queue_url``) started; ``None`` while it is still queued."""
        match = re.search(r"/queue/item/(\d+)/?$", urlparse(str(queue_url or "")).path)
        if match is None:
            raise JenkinsClientError("not a Jenkins queue item URL")
        data = await self._get_json(f"/queue/item/{match.group(1)}/api/json")
        number = dict(data.get("executable") or {}).get("number")
        return str(number) if number is not None else None

    async def get_logs(self, job_name: str, build_number: str | int, *, max_chars: int = 20000) -> dict[str, Any]:
        text = await self._get_text(f"{_job_path(job_name)}/{quote(str(build_number), safe='')}/consoleText")
        return {
            "job_name": job_name,
            "build_number": str(build_number),
            "truncated": len(text) > max_chars,
            "text": text[:max_chars],
        }

    async def get_artifacts(self, job_name: str, build_number: str | int) -> dict[str, Any]:
        data = await self._get_json(f"{_job_path(job_name)}/{quote(str(build_number), safe='')}/api/json")
        artifacts = [
            {
                "file_name": str(item.get("fileName") or item.get("file_name") or ""),
                "relative_path": str(item.get("relativePath") or item.get("relative_path") or ""),
                "display_path": str(item.get("displayPath") or item.get("display_path") or ""),
            }
            for item in data.get("artifacts") or []
            if isinstance(item, dict)
        ]
        return {"job_name": job_name, "build_number": str(build_number), "artifacts": artifacts}

    async def get_test_report(self, job_name: str, build_number: str | int) -> dict[str, Any]:
        data = await self._get_json(f"{_job_path(job_name)}/{quote(str(build_number), safe='')}/testReport/api/json")
        return {
            "job_name": job_name,
            "build_number": str(build_number),
            "fail_count": int(data.get("failCount") or 0),
            "skip_count": int(data.get("skipCount") or 0),
            "total_count": int(data.get("totalCount") or 0),
            "duration_seconds": data.get("duration"),
            "suites": data.get("suites") or [],
        }

    async def trigger_build(self, job_name: str, *, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = "buildWithParameters" if parameters else "build"
        response = await self._request("POST", f"{_job_path(job_name)}/{endpoint}", data=parameters or None)
        queue_url = response.headers.get("location") or response.headers.get("Location")
        return {"job_name": job_name, "queued": response.status_code in {200, 201, 202, 303}, "queue_url": queue_url}

    async def rerun_build(self, job_name: str, build_number: str | int) -> dict[str, Any]:
        current = await self.get_build_status(job_name, build_number)
        parameters = _extract_parameters(current.get("raw_actions") or [])
        result = await self.trigger_build(job_name, parameters=parameters or None)
        return {**result, "source_build_number": str(build_number), "parameters": parameters}

    async def cancel_build(self, job_name: str, build_number: str | int) -> dict[str, Any]:
        response = await self._request("POST", f"{_job_path(job_name)}/{quote(str(build_number), safe='')}/stop")
        return {
            "job_name": job_name,
            "build_number": str(build_number),
            "cancelled": response.status_code in {200, 201, 202, 302, 303},
        }

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._request("GET", path, params=params)
        try:
            data = response.json()
        except ValueError as exc:
            raise JenkinsClientError("Jenkins returned non-JSON response", status_code=response.status_code) from exc
        return data if isinstance(data, dict) else {}

    async def _get_text(self, path: str) -> str:
        response = await self._request("GET", path)
        return response.text

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"
        if self.config.username and self.config.token:
            kwargs["auth"] = (self.config.username, self.config.token)
        async with self._client_factory(timeout=self.config.timeout_seconds, follow_redirects=True) as client:
            response = await client.request(method, url, **kwargs)
        if response.status_code in {401, 403}:
            raise JenkinsClientError("Jenkins authentication failed", status_code=response.status_code)
        if response.status_code >= 400:
            raise JenkinsClientError(
                f"Jenkins request failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response


def _job_path(job_name: str) -> str:
    parts = [part for part in str(job_name).split("/") if part.strip()]
    return "".join(f"/job/{quote(part, safe='')}" for part in parts)


def _flatten_jobs(jobs: list[Any], *, parent: str = "") -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("fullName") or item.get("name") or "").strip()
        full_name = name if "/" in name or not parent else f"{parent}/{name}"
        if full_name:
            flattened.append(
                {
                    "name": full_name,
                    "display_name": str(item.get("name") or full_name),
                    "url": item.get("url"),
                    "color": item.get("color"),
                    "status": _color_to_status(item.get("color")),
                }
            )
        flattened.extend(_flatten_jobs(item.get("jobs") or [], parent=full_name))
    return flattened


def _normalize_build(job_name: str, data: dict[str, Any]) -> dict[str, Any]:
    result = data.get("result")
    building = bool(data.get("building"))
    status = "running" if building else _result_to_status(result)
    return {
        "job_name": job_name,
        "build_number": str(data.get("number") or ""),
        "build_url": data.get("url"),
        "status": status,
        "result": result,
        "building": building,
        "timestamp": data.get("timestamp"),
        "duration_ms": data.get("duration"),
        "raw_actions": data.get("actions") or [],
        # The commit the build built (Git plugin), so a caller can tie a build to a pushed commit.
        "commit": next((str(dict(item.get("lastBuiltRevision") or {}).get("SHA1") or "")
                        for item in data.get("actions") or []
                        if isinstance(item, dict) and isinstance(item.get("lastBuiltRevision"), dict)), ""),
    }


def _color_to_status(value: Any) -> str:
    color = str(value or "").lower()
    if color.startswith("blue"):
        return "passed"
    if color.startswith("red"):
        return "failed"
    if color.startswith("yellow"):
        return "unstable"
    if color.endswith("_anime"):
        return "running"
    return "unknown"


def _result_to_status(value: Any) -> str:
    result = str(value or "").lower()
    if result == "success":
        return "passed"
    if result == "failure":
        return "failed"
    if result == "unstable":
        return "unstable"
    if result == "aborted":
        return "cancelled"
    return "unknown"


def _extract_parameters(actions: list[Any]) -> dict[str, Any]:
    for action in actions:
        if not isinstance(action, dict):
            continue
        parameters = action.get("parameters")
        if isinstance(parameters, list):
            return {
                str(item.get("name")): item.get("value")
                for item in parameters
                if isinstance(item, dict) and item.get("name")
            }
    return {}
