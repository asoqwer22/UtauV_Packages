#!/usr/bin/env python3
"""
build_themes_index.py — Reference script for the UtauV_Packages repository.

Recursively scans the repository for theme manifest YAML files following the
expected layout:

    {git_username}/{theme_id}/{theme_name}.yaml

and regenerates themes.json in the repository root.

A manifest file is recognised as a UI-theme when its `type` field equals
"theme" (OuthemeMetadata) and as a singer-theme when `type` equals
"singer_theme" (OusthemeMetadata).  Both kinds are written into the same
themes.json array, distinguished by their "tags" field:
  - UI-theme:     tags = ["UtauV_Theme"]
  - Singer-theme: tags = ["UtauV_SingerTheme"]

The output format is a JSON array of RegistrySoftware-compatible objects that
PackageManager.FetchThemeRegistryAsync / FetchSingerThemeRegistryAsync can
consume directly.

Usage (from the repository root):
    python3 .github/scripts/build_themes_index.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_FILE = REPO_ROOT / "themes.json"
SKIP_DIRS: set[str] = {".git", ".github", "__pycache__", "node_modules"}
EXPECTED_DEPTH = 3 

def _normalize_slug(value: str) -> str:
    """Lowercase, replace non-alphanumeric/non-dot chars with '-', collapse dashes."""
    slug = re.sub(r"[^a-z0-9.]", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "unknown"


def build_theme_id(git_username: str, repo: str, theme_name: str) -> str:
    """Deterministic ID: {slug}.{hash8} — mirrors PackageManager.BuildThemeId."""
    slug = ".".join([
        _normalize_slug(git_username),
        _normalize_slug(repo),
        _normalize_slug(theme_name),
    ])
    raw = f"{git_username.strip()}/{repo.strip()}/{theme_name.strip()}"
    hash8 = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"{slug}.{hash8}"

def find_manifests(root: Path) -> list[tuple[Path, str, str]]:
    """
    Walk the repository and yield (yaml_path, git_username, theme_id) tuples
    for every YAML file found at depth 3 (root/username/theme_id/*.yaml).
    """
    results: list[tuple[Path, str, str]] = []
    for username_dir in sorted(root.iterdir()):
        if not username_dir.is_dir():
            continue
        if username_dir.name in SKIP_DIRS or username_dir.name.startswith("."):
            continue
        git_username = username_dir.name
        for theme_dir in sorted(username_dir.iterdir()):
            if not theme_dir.is_dir():
                continue
            theme_id_dir = theme_dir.name
            for yaml_file in sorted(theme_dir.glob("*.yaml")):
                results.append((yaml_file, git_username, theme_id_dir))
    return results

def manifest_to_registry_entry(
    yaml_path: Path,
    git_username: str,
    theme_id_dir: str,
    repo_name: str,
) -> dict[str, Any] | None:
    """
    Parse a theme manifest YAML and return a RegistrySoftware-compatible dict,
    or None if the file is not a recognised theme manifest.
    """
    try:
        with yaml_path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
    except Exception as exc:
        print(f"  WARNING: could not parse {yaml_path}: {exc}", file=sys.stderr)
        return None

    theme_type = str(data.get("type", "")).strip().lower()
    if theme_type not in ("theme", "singer_theme"):
        return None

    is_singer_theme = theme_type == "singer_theme"
    tag = "UtauV_SingerTheme" if is_singer_theme else "UtauV_Theme"

    theme_name = str(data.get("name") or yaml_path.stem).strip()
    author = str(data.get("author") or git_username).strip()
    version = str(data.get("version") or "1.0.0").strip()
    description = str(data.get("description") or "").strip()
    long_description = str(data.get("long_description") or "").strip()
    preview_image = str(data.get("preview_image") or "").strip()

    entry_id = str(data.get("id") or "").strip()
    if not entry_id:
        entry_id = build_theme_id(git_username, theme_id_dir, theme_name)
    raw_url = (
        f"https://raw.githubusercontent.com/emeraldsingers/UtauV_Packages"
        f"/refs/heads/main/{git_username}/{theme_id_dir}/{yaml_path.name}"
    )

    entry: dict[str, Any] = {
        "id": entry_id,
        "name": theme_name,
        "names": {"en": theme_name},
        "description": description,
        "descriptions": {"en": description} if description else {},
        "long_description": long_description,
        "tags": [tag],
        "developers": [author],
        "homepage_url": f"https://github.com/emeraldsingers/UtauV_Packages",
        "image_url": preview_image,
        "versions": [
            {
                "version": version,
                "description": f"Release {version}",
                "mirrors": [
                    {"url": raw_url, "hash": ""},
                ],
            }
        ],
    }

    if is_singer_theme:
        singers = str(data.get("singers") or "").strip()
        if singers:
            entry["singers"] = singers

    return entry

def main() -> None:
    print(f"Scanning {REPO_ROOT} for theme manifests …")
    manifests = find_manifests(REPO_ROOT)
    print(f"Found {len(manifests)} candidate YAML file(s).")

    repo_name = REPO_ROOT.name

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for yaml_path, git_username, theme_id_dir in manifests:
        entry = manifest_to_registry_entry(yaml_path, git_username, theme_id_dir, repo_name)
        if entry is None:
            continue
        entry_id = entry["id"]
        if entry_id in seen_ids:
            print(f"  WARNING: duplicate id '{entry_id}' from {yaml_path} — skipping.", file=sys.stderr)
            continue
        seen_ids.add(entry_id)
        entries.append(entry)
        tag = entry["tags"][0] if entry.get("tags") else "?"
        print(f"  [{tag}] {entry_id}  ({entry['name']})")

    entries.sort(key=lambda e: e.get("name", "").lower())

    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nWrote {len(entries)} entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
