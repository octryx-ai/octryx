from __future__ import annotations

import json
from typing import Any

from app.services.tool_result_compression.config import clamp_config_int


def _extract_kubectl_failed_pods(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    command = [str(part) for part in (result.get("command") or [])]
    stdout = str(result.get("stdout") or "")
    if not command or "pods" not in " ".join(command):
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    failures: list[dict[str, Any]] = []
    for pod in items:
        metadata = pod.get("metadata") or {}
        status = pod.get("status") or {}
        phase = str(status.get("phase") or "")
        container_statuses = status.get("containerStatuses") or []
        for cs in container_statuses:
            state = cs.get("state") or {}
            waiting = state.get("waiting") or {}
            terminated = state.get("terminated") or {}
            reason = str(waiting.get("reason") or terminated.get("reason") or "")
            if phase in {"Failed", "Unknown"} or reason in {
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "Error",
                "OOMKilled",
                "CreateContainerConfigError",
            }:
                failures.append(
                    {
                        "pod": metadata.get("name"),
                        "namespace": metadata.get("namespace"),
                        "phase": phase,
                        "reason": reason,
                        "restart_count": cs.get("restartCount", 0),
                        "container": cs.get("name"),
                    }
                )
                break
    max_items = clamp_config_int(config, "max_items", default=50, minimum=1, maximum=200)
    return {
        "command": command,
        "exit_code": result.get("exit_code"),
        "total_pods": len(items),
        "failed_count": len(failures),
        "failed_pods": failures[:max_items],
    }


def _compress_grafana_alerts(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    firing: list[dict[str, Any]] = []
    for alert in result.get("active") or []:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        status = alert.get("status") or {}
        state = str(status.get("state") or alert.get("state") or "").lower()
        if state and state != "firing":
            continue
        firing.append(
            {
                "alertname": labels.get("alertname"),
                "state": state or "firing",
                "severity": labels.get("severity"),
                "service": labels.get("service") or labels.get("job"),
                "summary": annotations.get("summary") or annotations.get("description"),
                "starts_at": alert.get("startsAt"),
            }
        )
    max_items = clamp_config_int(config, "max_items", default=50, minimum=1, maximum=100)
    return {
        "total_rules": result.get("total_rules"),
        "firing_alert_count": len(firing),
        "alerts": firing[:max_items],
    }


def _compress_loki_logs(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    tail_limit = clamp_config_int(config, "tail_lines", default=50, minimum=1, maximum=200)
    error_limit = clamp_config_int(config, "error_lines", default=50, minimum=1, maximum=200)
    tail_lines: list[dict[str, Any]] = []
    error_lines: list[dict[str, Any]] = []
    for stream in result.get("streams") or []:
        stream_labels = stream.get("stream") or {}
        values = stream.get("values") or []
        for ts, line in values[-tail_limit:]:
            tail_lines.append({"timestamp": ts, "line": line, "labels": stream_labels})
        for ts, line in values:
            lowered = str(line).lower()
            if any(token in lowered for token in ("error", "exception", "failed", "panic", "traceback")):
                error_lines.append({"timestamp": ts, "line": line, "labels": stream_labels})
    return {
        "query": result.get("query"),
        "total_lines": result.get("total_lines"),
        "streams_count": result.get("streams_count"),
        "tail_lines": tail_lines[-tail_limit:],
        "error_lines": error_lines[:error_limit],
    }
