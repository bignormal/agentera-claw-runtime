from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.desktop_runtime_channel import PLATFORM_TARGETS, build_runtime_channel


REPOSITORY = "bignormal/agentera-claw-runtime"
RELEASE_TAG = "v2026.7.7.2"


def _write_manifest(
    root: Path,
    platform: str,
    *,
    version: str = "0.18.2",
    repository: str = REPOSITORY,
    release_tag: str = RELEASE_TAG,
) -> None:
    target_os, target_arch = PLATFORM_TARGETS[platform]
    archive = f"hermes-runtime-hermes-agent-{version}-{platform}.tar.gz"
    manifest = {
        "schema": 2,
        "platform": platform,
        "targetOs": target_os,
        "targetArch": target_arch,
        "hermesAgentVersion": version,
        "provenance": {
            "release": {
                "repository": repository,
                "tag": release_tag,
            },
        },
        "asset": {
            "name": archive,
            "sha256": "a" * 64,
            "size": 123,
        },
    }
    (root / f"hermes-runtime-{platform}.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _write_all_manifests(root: Path) -> None:
    for platform in PLATFORM_TARGETS:
        _write_manifest(root, platform)


def _build(root: Path) -> dict[str, object]:
    return build_runtime_channel(
        root,
        release_tag=RELEASE_TAG,
        min_desktop_version="0.6.29",
        max_desktop_version="0.6.29",
        min_webui_version="0.6.29",
        max_webui_version="0.6.29",
    )


def test_builds_stable_channel_for_all_platforms(tmp_path: Path) -> None:
    _write_all_manifests(tmp_path)

    channel = _build(tmp_path)

    assert channel == {
        "schema": 1,
        "channel": "stable",
        "releaseTag": RELEASE_TAG,
        "runtimeVersion": "0.18.2",
        "minDesktopVersion": "0.6.29",
        "maxDesktopVersion": "0.6.29",
        "minWebUiVersion": "0.6.29",
        "maxWebUiVersion": "0.6.29",
        "platforms": {
            platform: {
                "descriptor": (
                    "https://github.com/"
                    f"{REPOSITORY}/releases/download/{RELEASE_TAG}/"
                    f"hermes-runtime-{platform}.json"
                )
            }
            for platform in PLATFORM_TARGETS
        },
    }


def test_requires_every_supported_platform_manifest(tmp_path: Path) -> None:
    _write_all_manifests(tmp_path)
    (tmp_path / "hermes-runtime-linux-arm64.json").unlink()

    with pytest.raises(FileNotFoundError):
        _build(tmp_path)


def test_rejects_mismatched_runtime_versions(tmp_path: Path) -> None:
    _write_all_manifests(tmp_path)
    _write_manifest(tmp_path, "linux-x64", version="0.18.3")

    with pytest.raises(ValueError, match="Runtime manifests disagree"):
        _build(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "NousResearch/hermes-agent"),
        ("release_tag", "v0.18.2"),
    ],
)
def test_rejects_manifest_from_another_release(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _write_all_manifests(tmp_path)
    kwargs = {field: value}
    _write_manifest(tmp_path, "mac-arm64", **kwargs)

    with pytest.raises(ValueError, match="release provenance"):
        _build(tmp_path)


@pytest.mark.parametrize(
    ("minimum", "maximum", "message"),
    [
        ("0.6.30", "0.6.29", "desktop compatibility minimum"),
        ("0.6.29", "", "invalid dotted version"),
        ("preview", "0.6.29", "invalid dotted version"),
    ],
)
def test_rejects_invalid_compatibility_range(
    tmp_path: Path,
    minimum: str,
    maximum: str,
    message: str,
) -> None:
    _write_all_manifests(tmp_path)

    with pytest.raises(ValueError, match=message):
        build_runtime_channel(
            tmp_path,
            release_tag=RELEASE_TAG,
            min_desktop_version=minimum,
            max_desktop_version=maximum,
            min_webui_version="0.6.29",
            max_webui_version="0.6.29",
        )


def test_rejects_invalid_webui_compatibility_range(tmp_path: Path) -> None:
    _write_all_manifests(tmp_path)

    with pytest.raises(ValueError, match="Web UI compatibility minimum"):
        build_runtime_channel(
            tmp_path,
            release_tag=RELEASE_TAG,
            min_desktop_version="0.6.29",
            max_desktop_version="0.6.29",
            min_webui_version="0.6.30",
            max_webui_version="0.6.29",
        )
