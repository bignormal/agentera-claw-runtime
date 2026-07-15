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
    assert workflow["jobs"]["build"]["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish"]["permissions"] == {"contents": "write"}
    assert workflow["jobs"]["publish"]["needs"] == "build"


def test_desktop_runtime_workflow_builds_the_complete_platform_matrix() -> None:
    workflow = _workflow()
    matrix = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
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
    publish_platforms = workflow["jobs"]["publish"]["strategy"]["matrix"][
        "platform"
    ]
    assert publish_platforms == list(targets)


def test_desktop_runtime_workflow_uses_tagged_local_source_and_pinned_builder() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "repository: bignormal/agentera-claw" in text
    assert "ref: ${{ vars.DESKTOP_RUNTIME_BUILDER_SHA }}" in text
    assert "actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38" in text
    assert "RUNTIME_PROVENANCE_SOURCE_COMMIT" in text
    assert "RUNTIME_PROVENANCE_BUILDER_COMMIT" in text
    assert "runtime-source[mcp,messaging,slack,wecom,dingtalk,feishu]" in text
    assert "hermes-agent[" not in text
    assert "==${{" not in text


def test_desktop_runtime_workflow_uses_scoped_key_for_private_builder() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    builder_checkout = next(
        step for step in steps if step["name"] == "Checkout immutable desktop builder"
    )

    assert builder_checkout["with"]["ssh-key"] == "${{ secrets.DESKTOP_RUNTIME_BUILDER_SSH_KEY }}"
    assert builder_checkout["with"]["persist-credentials"] == "false"

    secret_reference = "secrets.DESKTOP_RUNTIME_BUILDER_SSH_KEY"
    other_steps = [step for step in steps if step is not builder_checkout]
    assert all(secret_reference not in str(step) for step in other_steps)


def test_desktop_runtime_workflow_never_silently_clobbers_assets() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "replace_existing" in text
    assert "gh release delete-asset" in text
    upload_lines = [line for line in text.splitlines() if "gh release upload" in line]
    assert upload_lines
    assert all("--clobber" not in line for line in upload_lines)


def test_desktop_runtime_workflow_does_not_expose_write_token_to_runtime_build() -> None:
    workflow = _workflow()
    build_steps = workflow["jobs"]["build"]["steps"]
    publish_steps = workflow["jobs"]["publish"]["steps"]
    prepare = next(
        step
        for step in build_steps
        if step["name"] == "Prepare Runtime from tagged local source"
    )
    upload = next(
        step
        for step in publish_steps
        if step["name"] == "Upload immutable Runtime assets"
    )

    assert "GH_TOKEN" not in prepare.get("env", {})
    assert upload["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert all("gh release upload" not in str(step) for step in build_steps)
    assert all("runtime-source" not in str(step) for step in publish_steps)
    assert all("runtime-builder" not in str(step) for step in publish_steps)
    assert all(
        "DESKTOP_RUNTIME_BUILDER_SSH_KEY" not in str(step) for step in publish_steps
    )


def test_desktop_runtime_workflow_validates_complete_existing_asset_set() -> None:
    build_steps = _workflow()["jobs"]["build"]["steps"]
    assets = next(
        step for step in build_steps if step["name"] == "Stage complete Runtime bundle"
    )
    script = assets["run"]

    assert '--pattern "$ASSET"' in script
    assert '--pattern "$ASSET.sha256"' in script
    assert '--pattern "$MANIFEST"' in script
    assert "--allow-missing-archives" not in script


def test_desktop_runtime_workflow_keeps_expressions_out_of_shell_scripts() -> None:
    workflow = _workflow()
    shell_steps = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]
    assert all("${{" not in step["run"] for step in shell_steps)


def test_desktop_runtime_workflow_disables_release_dependency_caches() -> None:
    build_steps = _workflow()["jobs"]["build"]["steps"]
    setup_node = next(step for step in build_steps if step["name"] == "Setup Node.js")
    setup_uv = next(step for step in build_steps if step["name"] == "Install uv")

    assert "cache" not in setup_node["with"]
    assert setup_node["with"]["package-manager-cache"] == "false"
    assert setup_uv["with"]["enable-cache"] == "false"
