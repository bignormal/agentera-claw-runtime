from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path


PLATFORM_TARGETS = {
    "mac-arm64": ("darwin", "arm64"),
    "mac-x64": ("darwin", "x64"),
    "win-x64": ("win32", "x64"),
    "linux-x64": ("linux", "x64"),
    "linux-arm64": ("linux", "arm64"),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_release_directory(
    directory: Path,
    *,
    platforms: Iterable[str],
    release_repository: str,
    release_tag: str,
    source_commit: str,
    builder_commit: str,
    require_archives: bool = True,
) -> str:
    versions: set[str] = set()
    for platform in platforms:
        target_os, target_arch = PLATFORM_TARGETS[platform]
        manifest_path = directory / f"hermes-runtime-{platform}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _expect(manifest.get("schema"), 2, f"{platform} schema")
        _expect(manifest.get("platform"), platform, f"{platform} platform")
        _expect(manifest.get("targetOs"), target_os, f"{platform} target OS")
        _expect(manifest.get("targetArch"), target_arch, f"{platform} target architecture")

        version = manifest.get("hermesAgentVersion")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{platform} hermesAgentVersion is missing")
        versions.add(version)

        provenance = manifest.get("provenance", {})
        _expect(
            provenance.get("release"),
            {"repository": release_repository, "tag": release_tag},
            f"{platform} release provenance",
        )
        _expect(
            provenance.get("source"),
            {
                "repository": release_repository,
                "ref": release_tag,
                "commit": source_commit,
            },
            f"{platform} source commit",
        )
        _expect(
            provenance.get("builder"),
            {
                "repository": "bignormal/agentera-claw",
                "commit": builder_commit,
            },
            f"{platform} builder commit",
        )

        asset = manifest.get("asset", {})
        asset_name = f"hermes-runtime-hermes-agent-{version}-{platform}.tar.gz"
        _expect(asset.get("name"), asset_name, f"{platform} archive name")
        digest = asset.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"{platform} SHA-256 is invalid")

        sidecar_path = directory / f"{asset_name}.sha256"
        sidecar_digest, sidecar_name = sidecar_path.read_text(
            encoding="utf-8"
        ).strip().split(maxsplit=1)
        _expect(sidecar_digest, digest, f"{platform} sidecar SHA-256")
        _expect(sidecar_name, asset_name, f"{platform} sidecar archive name")

        archive_path = directory / asset_name
        if require_archives:
            _expect(archive_path.stat().st_size, asset.get("size"), f"{platform} archive size")
            _expect(_sha256(archive_path), digest, f"{platform} SHA-256")
        elif archive_path.exists():
            _expect(archive_path.stat().st_size, asset.get("size"), f"{platform} archive size")
            _expect(_sha256(archive_path), digest, f"{platform} SHA-256")

    if len(versions) != 1:
        raise ValueError(f"Runtime manifests disagree on package version: {sorted(versions)}")
    return versions.pop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--platform", action="append", dest="platforms", required=True)
    parser.add_argument("--release-repository", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--builder-commit", required=True)
    parser.add_argument("--allow-missing-archives", action="store_true")
    args = parser.parse_args()
    version = validate_release_directory(
        args.directory,
        platforms=args.platforms,
        release_repository=args.release_repository,
        release_tag=args.release_tag,
        source_commit=args.source_commit,
        builder_commit=args.builder_commit,
        require_archives=not args.allow_missing_archives,
    )
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
