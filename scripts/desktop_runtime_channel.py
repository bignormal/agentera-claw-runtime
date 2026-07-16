from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PLATFORM_TARGETS = {
    "mac-arm64": ("darwin", "arm64"),
    "mac-x64": ("darwin", "x64"),
    "win-x64": ("win32", "x64"),
    "linux-x64": ("linux", "x64"),
    "linux-arm64": ("linux", "arm64"),
}
REPOSITORY = "bignormal/agentera-claw-runtime"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = value.removeprefix("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid dotted version: {value!r}")
    return tuple(int(part) for part in parts)


def _expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ValueError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _validate_compatibility_range(
    minimum: str,
    maximum: str,
    label: str,
) -> None:
    minimum_tuple = _version_tuple(minimum)
    maximum_tuple = _version_tuple(maximum)
    width = max(len(minimum_tuple), len(maximum_tuple))
    padded_minimum = minimum_tuple + (0,) * (width - len(minimum_tuple))
    padded_maximum = maximum_tuple + (0,) * (width - len(maximum_tuple))
    if padded_minimum > padded_maximum:
        raise ValueError(f"{label} compatibility minimum exceeds maximum")


def build_runtime_channel(
    directory: Path,
    *,
    release_tag: str,
    min_desktop_version: str,
    max_desktop_version: str,
    min_webui_version: str,
    max_webui_version: str,
) -> dict[str, object]:
    if not release_tag:
        raise ValueError("Runtime release tag must not be empty")
    _validate_compatibility_range(
        min_desktop_version,
        max_desktop_version,
        "desktop",
    )
    _validate_compatibility_range(
        min_webui_version,
        max_webui_version,
        "Web UI",
    )

    versions: set[str] = set()
    platforms: dict[str, dict[str, str]] = {}
    for platform, (target_os, target_arch) in PLATFORM_TARGETS.items():
        manifest_path = directory / f"hermes-runtime-{platform}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _expect(manifest.get("schema"), 2, f"{platform} schema")
        _expect(manifest.get("platform"), platform, f"{platform} platform")
        _expect(manifest.get("targetOs"), target_os, f"{platform} target OS")
        _expect(
            manifest.get("targetArch"),
            target_arch,
            f"{platform} target architecture",
        )

        version = manifest.get("hermesAgentVersion")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{platform} Runtime version is missing")
        versions.add(version)

        release = manifest.get("provenance", {}).get("release", {})
        expected_release = {"repository": REPOSITORY, "tag": release_tag}
        _expect(release, expected_release, f"{platform} release provenance")

        asset = manifest.get("asset", {})
        expected_asset = f"hermes-runtime-hermes-agent-{version}-{platform}.tar.gz"
        _expect(asset.get("name"), expected_asset, f"{platform} archive name")
        if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
            raise ValueError(f"{platform} archive size is invalid")
        if not isinstance(asset.get("sha256"), str) or not SHA256.fullmatch(
            asset["sha256"]
        ):
            raise ValueError(f"{platform} archive SHA-256 is invalid")

        platforms[platform] = {
            "descriptor": (
                f"https://github.com/{REPOSITORY}/releases/download/"
                f"{release_tag}/hermes-runtime-{platform}.json"
            )
        }

    if len(versions) != 1:
        raise ValueError(f"Runtime manifests disagree: {sorted(versions)}")

    return {
        "schema": 1,
        "channel": "stable",
        "releaseTag": release_tag,
        "runtimeVersion": versions.pop(),
        "minDesktopVersion": min_desktop_version,
        "maxDesktopVersion": max_desktop_version,
        "minWebUiVersion": min_webui_version,
        "maxWebUiVersion": max_webui_version,
        "platforms": platforms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--min-desktop-version", required=True)
    parser.add_argument("--max-desktop-version", required=True)
    parser.add_argument("--min-webui-version", required=True)
    parser.add_argument("--max-webui-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    channel = build_runtime_channel(
        args.directory,
        release_tag=args.release_tag,
        min_desktop_version=args.min_desktop_version,
        max_desktop_version=args.max_desktop_version,
        min_webui_version=args.min_webui_version,
        max_webui_version=args.max_webui_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(channel, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
