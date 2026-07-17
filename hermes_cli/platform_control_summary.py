"""Privacy-bounded summaries for the optional AgentEra platform control client."""

from __future__ import annotations

import platform
import time
from typing import Any, Dict, Mapping, Optional

from hermes_cli import __version__

_RESOURCE_FIELDS = {
    "tasks": {"id", "status", "source", "model", "tokens", "cost", "errorCode"},
    "workflows": {"id", "status", "version", "nodeCount", "failedNode"},
    "cron": {"id", "status", "nextRunAt", "lastResult"},
    "codingAgents": {"id", "type", "status", "durationMs", "changeCount", "workspaceHash"},
    "devices": {"id", "type", "status", "lastSeenAt"},
}


def _bounded_resources(resources: Optional[Mapping[str, Any]]) -> Dict[str, list]:
    source = resources if isinstance(resources, Mapping) else {}
    result: Dict[str, list] = {}
    for kind, allowed in _RESOURCE_FIELDS.items():
        rows = source.get(kind, [])
        if not isinstance(rows, list):
            rows = []
        sanitized = []
        for row in rows[:100]:
            if not isinstance(row, Mapping):
                continue
            clean = {key: value for key, value in row.items() if key in allowed}
            if clean.get("id") and clean.get("status"):
                sanitized.append(clean)
        result[kind] = sanitized
    return result


def _channel_summaries(config: Mapping[str, Any]) -> list:
    providers = config.get("providers", {})
    if not isinstance(providers, Mapping):
        return []
    return [
        {"type": str(name)[:80], "configured": bool(value)}
        for name, value in list(providers.items())[:100]
        if str(name).strip()
    ]


def build_platform_control_summary(
    *,
    config: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the strict heartbeat schema without content, paths, logs, or secrets."""
    cfg = config if isinstance(config, Mapping) else {}
    bounded = _bounded_resources(resources)
    return {
        "version": __version__,
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "uptimeSeconds": max(0, int(time.monotonic())),
        "capabilities": ["diagnostics.health.read"],
        "metrics": {
            "taskCount": len(bounded["tasks"]),
            "workflowCount": len(bounded["workflows"]),
            "cronCount": len(bounded["cron"]),
        },
        "channels": _channel_summaries(cfg),
        "resources": bounded,
    }


def build_health_check_result() -> Dict[str, Any]:
    summary = build_platform_control_summary(config={})
    return {
        "gateway": "running",
        "version": summary["version"],
        "counts": summary["metrics"],
    }
