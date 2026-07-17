import asyncio
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.platform_control import (
    DeviceUnauthorized,
    PlatformControlClient,
    PlatformIdentity,
    enroll,
    load_identity,
    start_platform_control_if_enabled,
)
from hermes_cli.platform_control_summary import build_platform_control_summary


class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def test_default_configuration_starts_no_network_task(hermes_home):
    with patch("hermes_cli.platform_control.urllib.request.urlopen") as request:
        task = start_platform_control_if_enabled(asyncio.Event(), config={})
    assert task is None
    request.assert_not_called()


@pytest.mark.asyncio
async def test_enroll_stores_only_identity_with_owner_permissions(hermes_home):
    def opener(request, timeout=0):
        assert request.full_url == "https://platform.example/api/control/v1/enroll"
        body = json.loads(request.data)
        assert body["enrollmentCode"] == "one-time-code"
        return FakeResponse(
            {
                "data": {
                    "deviceSecret": "device-secret",
                    "heartbeatSeconds": 60,
                    "instanceId": "7",
                },
                "meta": {},
                "requestId": "enroll-1",
            }
        )

    identity = await enroll(
        "https://platform.example",
        "one-time-code",
        opener=opener,
        device_id="device-1",
    )
    assert identity == PlatformIdentity(instance_id="7", device_secret="device-secret")
    stored = (hermes_home / "platform-control.json").read_text()
    assert "one-time-code" not in stored
    assert load_identity() == identity
    if os.name == "posix":
        assert stat.S_IMODE((hermes_home / "platform-control.json").stat().st_mode) == 0o600


def test_summary_is_bounded_and_contains_no_content_fields(hermes_home):
    summary = build_platform_control_summary(
        config={"providers": {"openai": {"api_key": "must-not-leak"}}},
        resources={
            "tasks": [
                {"id": str(index), "status": "done", "source": "cron", "prompt": "private"}
                for index in range(120)
            ]
        },
    )
    serialized = json.dumps(summary)
    assert len(summary["resources"]["tasks"]) == 100
    assert "private" not in serialized
    assert "must-not-leak" not in serialized
    assert "prompt" not in serialized


@pytest.mark.asyncio
async def test_heartbeat_executes_only_health_check_and_401_stops_client(hermes_home):
    calls = []

    def opener(request, timeout=0):
        calls.append((request.full_url, json.loads(request.data)))
        if request.full_url.endswith("/heartbeat"):
            return FakeResponse(
                {
                    "data": {
                        "acceptedAt": "2026-07-16T00:00:00Z",
                        "command": {"id": "9", "type": "health_check"},
                        "nextHeartbeatSeconds": 60,
                    },
                    "meta": {},
                    "requestId": "heartbeat-1",
                }
            )
        return FakeResponse({"data": {"accepted": True}, "meta": {}, "requestId": "result-1"})

    client = PlatformControlClient(
        endpoint="https://platform.example",
        identity=PlatformIdentity("7", "device-secret"),
        opener=opener,
        summary_provider=lambda: build_platform_control_summary(config={}),
    )
    await client.heartbeat_once()
    assert calls[0][0].endswith("/api/control/v1/heartbeat")
    assert calls[1][0].endswith("/api/control/v1/commands/9/result")
    assert calls[1][1]["state"] == "succeeded"
    assert "HEALTHY" == calls[1][1]["code"]

    def unauthorized(_request, timeout=0):
        from urllib.error import HTTPError

        raise HTTPError("https://platform.example", 401, "unauthorized", {}, None)

    client = PlatformControlClient(
        endpoint="https://platform.example",
        identity=PlatformIdentity("7", "bad"),
        opener=unauthorized,
        summary_provider=lambda: build_platform_control_summary(config={}),
    )
    with pytest.raises(DeviceUnauthorized):
        await client.heartbeat_once()
    assert client.disabled is True


@pytest.mark.asyncio
async def test_run_cancels_promptly_when_stop_is_set(hermes_home):
    stop = asyncio.Event()
    client = PlatformControlClient(
        endpoint="https://platform.example",
        identity=PlatformIdentity("7", "device-secret"),
        heartbeat_seconds=60,
        opener=lambda *_args, **_kwargs: FakeResponse(
            {"data": {"command": None, "nextHeartbeatSeconds": 60}, "meta": {}, "requestId": "1"}
        ),
        summary_provider=lambda: build_platform_control_summary(config={}),
    )
    task = asyncio.create_task(client.run(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
