from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "desktop-runtime.yml"


def _workflow() -> dict:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_desktop_runtime_workflow_has_controlled_triggers_and_permissions() -> None:
    workflow = _workflow()
    assert set(workflow["on"]) == {"release", "workflow_dispatch"}
    assert workflow["on"]["release"]["types"] == ["published"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["runtime"]["permissions"] == {"contents": "write"}


def test_desktop_runtime_workflow_builds_the_complete_platform_matrix() -> None:
    matrix = _workflow()["jobs"]["runtime"]["strategy"]["matrix"]["include"]
    targets = {
        entry["platform"]: (
            entry["runner"],
            entry["target_os"],
            entry["target_arch"],
        )
        for entry in matrix
    }
    assert len(matrix) == 5
    assert targets == {
        "mac-arm64": ("macos-15", "darwin", "arm64"),
        "mac-x64": ("macos-15-intel", "darwin", "x64"),
        "win-x64": ("windows-latest", "win32", "x64"),
        "linux-x64": ("ubuntu-22.04", "linux", "x64"),
        "linux-arm64": ("ubuntu-22.04-arm", "linux", "arm64"),
    }


def test_desktop_runtime_workflow_uses_tagged_local_source_and_pinned_builder() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "repository: bignormal/agentera-claw" in text
    assert "ref: ${{ vars.DESKTOP_RUNTIME_BUILDER_SHA }}" in text
    assert "RUNTIME_PROVENANCE_SOURCE_COMMIT" in text
    assert "RUNTIME_PROVENANCE_BUILDER_COMMIT" in text
    assert "runtime-source[mcp,messaging,slack,wecom,dingtalk,feishu]" in text
    assert "hermes-agent[" not in text
    assert "==${{" not in text


def test_desktop_runtime_workflow_never_silently_clobbers_assets() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "replace_existing" in text
    assert "gh release delete-asset" in text
    upload_lines = [line for line in text.splitlines() if "gh release upload" in line]
    assert upload_lines
    assert all("--clobber" not in line for line in upload_lines)
