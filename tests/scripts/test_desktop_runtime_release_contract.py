from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.desktop_runtime_release_contract import validate_release_directory


SOURCE_COMMIT = "9de9c25f620ff7f1ce0fd5457d596052d5159596"
BUILDER_COMMIT = "c621b20225f529656707380b8bc5f7535d32cbfd"


def _write_contract(root: Path, platform: str = "mac-arm64") -> None:
    archive = root / f"hermes-runtime-hermes-agent-0.18.2-{platform}.tar.gz"
    archive.write_bytes(b"portable-runtime")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (root / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": 2,
        "platform": platform,
        "targetOs": "darwin",
        "targetArch": "arm64",
        "hermesAgentVersion": "0.18.2",
        "provenance": {
            "release": {
                "repository": "bignormal/agentera-claw-runtime",
                "tag": "v2026.7.7.2",
            },
            "source": {
                "repository": "bignormal/agentera-claw-runtime",
                "ref": "v2026.7.7.2",
                "commit": SOURCE_COMMIT,
            },
            "builder": {
                "repository": "bignormal/agentera-claw",
                "commit": BUILDER_COMMIT,
            },
        },
        "asset": {
            "name": archive.name,
            "sha256": digest,
            "size": archive.stat().st_size,
        },
    }
    (root / f"hermes-runtime-{platform}.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_validates_archive_sidecar_and_provenance(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    version = validate_release_directory(
        tmp_path,
        platforms=["mac-arm64"],
        release_repository="bignormal/agentera-claw-runtime",
        release_tag="v2026.7.7.2",
        source_commit=SOURCE_COMMIT,
        builder_commit=BUILDER_COMMIT,
    )
    assert version == "0.18.2"


def test_rejects_a_digest_mismatch(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    manifest_path = tmp_path / "hermes-runtime-mac-arm64.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["asset"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_release_directory(
            tmp_path,
            platforms=["mac-arm64"],
            release_repository="bignormal/agentera-claw-runtime",
            release_tag="v2026.7.7.2",
            source_commit=SOURCE_COMMIT,
            builder_commit=BUILDER_COMMIT,
        )


def test_rejects_wrong_source_provenance(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    with pytest.raises(ValueError, match="source commit"):
        validate_release_directory(
            tmp_path,
            platforms=["mac-arm64"],
            release_repository="bignormal/agentera-claw-runtime",
            release_tag="v2026.7.7.2",
            source_commit="a" * 40,
            builder_commit=BUILDER_COMMIT,
        )
