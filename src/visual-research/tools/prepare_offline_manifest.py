#!/usr/bin/env python3
"""Create a local-only Minecraft launcher manifest from NeoForm's cache."""

import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def property_value(name: str) -> str:
    for raw_line in (ROOT / "gradle.properties").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    raise RuntimeError(f"missing Gradle property: {name}")


def main() -> int:
    version = property_value("minecraft_version")
    gradle_home = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle"))
    artifacts = gradle_home / "caches" / "neoformruntime" / "artifacts"
    launcher_path = artifacts / "minecraft_launcher_manifest.json"
    version_path = artifacts / f"minecraft_{version}_version_manifest.json"
    if not launcher_path.is_file() or not version_path.is_file():
        print("NeoForm's cached Minecraft manifests are missing; refusing an online test run.", file=sys.stderr)
        return 2

    launcher = json.loads(launcher_path.read_text(encoding="utf-8"))
    version_manifest = json.loads(version_path.read_text(encoding="utf-8"))
    if version_manifest.get("id") != version:
        raise RuntimeError(f"cached version manifest is for {version_manifest.get('id')}, not {version}")

    selected = next((entry for entry in launcher.get("versions", []) if entry.get("id") == version), None)
    if selected is None:
        raise RuntimeError(f"launcher cache has no Minecraft {version} entry")

    output_dir = ROOT / "build" / "low-memory"
    output_dir.mkdir(parents=True, exist_ok=True)
    asset = version_manifest.get("assetIndex", {})
    asset_id = str(asset.get("id", ""))
    cached_asset_index = gradle_home / "caches" / "neoformruntime" / "assets" / "indexes" / f"{asset_id}.json"
    if not cached_asset_index.is_file():
        print("NeoForm's cached asset index is missing; refusing an online test run.", file=sys.stderr)
        return 2
    asset_bytes = cached_asset_index.read_bytes()
    asset_index = json.loads(asset_bytes)
    asset_objects = gradle_home / "caches" / "neoformruntime" / "assets" / "objects"
    missing_assets = []
    for entry in asset_index.get("objects", {}).values():
        digest = str(entry.get("hash", ""))
        if len(digest) != 40 or not (asset_objects / digest[:2] / digest).is_file():
            missing_assets.append(digest or "<invalid>")
            if len(missing_assets) == 5:
                break
    if missing_assets:
        print(
            "NeoForm's cached assets are incomplete; refusing an online test run "
            f"(examples: {', '.join(missing_assets)}).",
            file=sys.stderr,
        )
        return 2
    asset["url"] = cached_asset_index.resolve().as_uri()
    asset["sha1"] = hashlib.sha1(asset_bytes).hexdigest()
    asset["size"] = len(asset_bytes)

    local_version = output_dir / f"minecraft-{version}-version-manifest.json"
    local_version.write_text(
        json.dumps(version_manifest, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected["url"] = local_version.resolve().as_uri()
    selected["sha1"] = hashlib.sha1(local_version.read_bytes()).hexdigest()

    output = output_dir / "cached-minecraft-launcher-manifest.json"
    output.write_text(json.dumps(launcher, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
