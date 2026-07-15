"""Opt-in outbound control client for an AgentEra-managed Runtime instance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from hermes_constants import get_hermes_home
from hermes_cli import __version__
from hermes_cli.config import cfg_get, load_config, read_raw_config, save_config
from hermes_cli.platform_control_summary import (
    build_health_check_result,
    build_platform_control_summary,
)


@dataclass(frozen=True)
class PlatformIdentity:
    instance_id: str
    device_secret: str


class DeviceUnauthorized(RuntimeError):
    """Raised when the platform rejects the stored one-time device identity."""


def identity_path() -> Path:
    return Path(get_hermes_home()) / "platform-control.json"


def _write_identity(identity: PlatformIdentity) -> None:
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".platform-control-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {"instanceId": identity.instance_id, "deviceSecret": identity.device_secret},
                handle,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_identity() -> Optional[PlatformIdentity]:
    try:
        value = json.loads(identity_path().read_text(encoding="utf-8"))
        instance_id = value.get("instanceId")
        device_secret = value.get("deviceSecret")
        if isinstance(instance_id, str) and instance_id and isinstance(device_secret, str) and device_secret:
            return PlatformIdentity(instance_id, device_secret)
    except (OSError, ValueError, TypeError):
        pass
    return None


def _valid_endpoint(endpoint: str) -> str:
    from urllib.parse import urlparse

    normalized = endpoint.strip().rstrip("/")
    parsed = urlparse(normalized)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("Platform endpoint must use HTTPS (HTTP is allowed only for loopback development).")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid platform endpoint.")
    return normalized


def _default_device_id() -> str:
    value = f"{platform.node()}:{uuid.getnode()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sync_post(
    opener: Callable[..., Any],
    url: str,
    body: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with opener(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        raise RuntimeError("Invalid platform control response.")
    return data["data"]


async def enroll(
    endpoint: str,
    enrollment_code: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    device_id: Optional[str] = None,
) -> PlatformIdentity:
    normalized = _valid_endpoint(endpoint)
    summary = build_platform_control_summary(config={})
    body = {
        "enrollmentCode": enrollment_code,
        "instanceType": "runtime",
        "deviceId": device_id or _default_device_id(),
        "version": __version__,
        "os": summary["os"],
        "arch": summary["arch"],
        "capabilities": ["diagnostics.health.read"],
    }
    data = await asyncio.to_thread(
        _sync_post,
        opener,
        f"{normalized}/api/control/v1/enroll",
        body,
    )
    identity = PlatformIdentity(str(data["instanceId"]), str(data["deviceSecret"]))
    _write_identity(identity)

    config = read_raw_config()
    config["platform_control"] = {
        "enabled": True,
        "endpoint": normalized,
        "heartbeat_seconds": max(15, min(300, int(data.get("heartbeatSeconds", 60)))),
    }
    save_config(config, preserve_keys={("platform_control",)})
    return identity


class PlatformControlClient:
    def __init__(
        self,
        *,
        endpoint: str,
        identity: PlatformIdentity,
        heartbeat_seconds: int = 60,
        opener: Callable[..., Any] = urllib.request.urlopen,
        summary_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.endpoint = _valid_endpoint(endpoint)
        self.identity = identity
        self.heartbeat_seconds = max(15, min(300, int(heartbeat_seconds)))
        self.opener = opener
        self.summary_provider = summary_provider or (
            lambda: build_platform_control_summary(config=load_config())
        )
        self.disabled = False

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(
                _sync_post,
                self.opener,
                f"{self.endpoint}{path}",
                body,
                {
                    "Authorization": f"Bearer {self.identity.device_secret}",
                    "X-AgentEra-Instance-ID": self.identity.instance_id,
                },
            )
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.disabled = True
                raise DeviceUnauthorized("Device identity was rejected; re-enroll is required.") from error
            raise

    async def execute(self, command: Dict[str, Any]) -> Dict[str, Any]:
        command_id = str(command.get("id", ""))
        if command.get("type") == "health_check" and command_id:
            result = {"state": "succeeded", "code": "HEALTHY", "summary": build_health_check_result()}
        else:
            result = {
                "state": "failed",
                "code": "UNSUPPORTED_COMMAND",
                "summary": {"status": "unsupported"},
            }
        if command_id:
            await self._post(f"/api/control/v1/commands/{command_id}/result", result)
        return result

    async def heartbeat_once(self) -> Dict[str, Any]:
        if self.disabled:
            raise DeviceUnauthorized("Device identity is disabled; re-enroll is required.")
        data = await self._post("/api/control/v1/heartbeat", self.summary_provider())
        command = data.get("command")
        if isinstance(command, dict):
            await self.execute(command)
        return data

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = 1.0
        while not stop_event.is_set() and not self.disabled:
            try:
                data = await self.heartbeat_once()
                delay = max(15, min(300, int(data.get("nextHeartbeatSeconds", self.heartbeat_seconds))))
                backoff = 1.0
            except DeviceUnauthorized:
                return
            except (OSError, ValueError, RuntimeError, urllib.error.URLError):
                delay = backoff
                backoff = min(300.0, backoff * 2)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue


def start_platform_control_if_enabled(
    stop_event: asyncio.Event,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[asyncio.Task]:
    resolved = load_config() if config is None else config
    enabled = bool(cfg_get(resolved, "platform_control", "enabled", default=False))
    endpoint = cfg_get(resolved, "platform_control", "endpoint", default="")
    identity = load_identity()
    if not enabled or not isinstance(endpoint, str) or not endpoint.strip() or identity is None:
        return None
    client = PlatformControlClient(
        endpoint=endpoint,
        identity=identity,
        heartbeat_seconds=int(
            cfg_get(resolved, "platform_control", "heartbeat_seconds", default=60) or 60
        ),
    )
    return asyncio.create_task(client.run(stop_event), name="platform-control")
