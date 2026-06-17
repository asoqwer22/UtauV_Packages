#!/usr/bin/env python3
"""
build_themes_index.py — Reference script for the UtauV_Packages repository.

Recursively scans the repository for theme manifest YAML files.  Any YAML
file whose ``type`` field equals ``"theme"`` or ``"singer_theme"`` is treated
as a theme manifest.  The expected (but not required) layout is:

    {git_username}/{theme_id}/{theme_name}.yaml

The script is fully recursive: it walks the entire repository tree via
``Path.rglob``, skipping hidden directories and the directories listed in
``SKIP_DIRS``.  ``git_username`` and ``theme_id`` are taken from the manifest
fields ``git_username`` / ``id`` when present; otherwise they are derived from
the first two path segments relative to the repository root.

Output format
-------------
A JSON array of RegistrySoftware-compatible objects written to ``themes.json``
in the repository root.  Each entry carries two extra fields that are silently
ignored by Newtonsoft.Json (RegistrySoftware deserialization):

* ``palette``        – dict of every non-meta key from the manifest (all
                       ``*_color`` keys, ``is_dark_mode``, and any other
                       unrecognised keys), preserving original key names.
* ``theme_manifest`` – the full raw manifest dict as parsed from YAML.

These fields allow the Package Manager UI to render a colour-accurate
mini-preview without downloading the full YAML file.

URL encoding
------------
The ``mirror.url`` for each entry is built from the *real* relative path of
the YAML file inside the repository, with every path segment individually
percent-encoded via ``urllib.parse.quote`` (slashes are preserved as ``/``).
This prevents 400 Bad Request errors when file or directory names contain
spaces or other special characters.

Usage (from the repository root):
    python3 .github/scripts/build_themes_index.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_FILE = REPO_ROOT / "themes.json"
SKIP_DIRS: set[str] = {".git", ".github", "__pycache__", "node_modules"}
RAW_BASE_URL = (
    "https://raw.githubusercontent.com/emeraldsingers/UtauV_Packages"
    "/refs/heads/main"
)
META_KEYS: set[str] = {
    "type",
    "id",
    "name",
    "author",
    "version",
    "description",
    "long_description",
    "git_username",
    "repo",
    "preview_image",
    "singers",
    "tags",
}

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

def encode_path(rel_path: Path) -> str:
    """
    Return a URL-safe string for *rel_path* by percent-encoding each segment
    individually (spaces → %20, etc.) while keeping forward slashes intact.

    Example:
        encode_path(Path("asoqwer22/test_theme/high contrast.yaml"))
        → "asoqwer22/test_theme/high%20contrast.yaml"
    """
    parts = rel_path.as_posix().split("/")
    return "/".join(quote(part, safe="") for part in parts)


def build_raw_url(rel_path: Path) -> str:
    """Build the raw.githubusercontent.com URL for a file at *rel_path*."""
    return f"{RAW_BASE_URL}/{encode_path(rel_path)}"

def find_manifests(root: Path) -> list[tuple[Path, str, str]]:
    """
    Recursively walk *root* and return ``(yaml_path, git_username, theme_id)``
    tuples for every YAML file that declares ``type: theme`` or
    ``type: singer_theme``.

    * Hidden directories (name starts with ``"."``) and directories listed in
      ``SKIP_DIRS`` are skipped at every level.
    * ``git_username`` and ``theme_id`` are taken from the manifest fields
      ``git_username`` / ``id`` when present; otherwise they are derived from
      the first two path segments relative to *root*.
    * Prints a diagnostic summary: total YAML files found and how many are
      recognised theme manifests.
    """
    all_yaml: list[Path] = []

    for candidate in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        rel = candidate.relative_to(root)
        parts = rel.parts
        skip = False
        for part in parts[:-1]:  # directory components only
            if part in SKIP_DIRS or part.startswith("."):
                skip = True
                break
        if skip:
            continue
        all_yaml.append(candidate)

    print(f"  Total YAML files found: {len(all_yaml)}")

    results: list[tuple[Path, str, str]] = []

    for yaml_path in all_yaml:
        try:
            with yaml_path.open(encoding="utf-8") as fh:
                data: dict[str, Any] = yaml.safe_load(fh) or {}
        except Exception as exc:
            print(f"  WARNING: could not parse {yaml_path}: {exc}", file=sys.stderr)
            continue

        theme_type = str(data.get("type", "")).strip().lower()
        if theme_type not in ("theme", "singer_theme"):
            continue
        rel = yaml_path.relative_to(root)
        path_parts = rel.parts  # e.g. ("asoqwer22", "test_theme", "high_contrast.yaml")

        git_username = str(data.get("git_username") or "").strip()
        if not git_username and len(path_parts) >= 1:
            git_username = path_parts[0]
        git_username = git_username or "unknown"

        theme_id_dir = str(data.get("id") or "").strip()
        if not theme_id_dir and len(path_parts) >= 2:
            theme_id_dir = path_parts[1]
        theme_id_dir = theme_id_dir or yaml_path.stem

        results.append((yaml_path, git_username, theme_id_dir))

    print(f"  Theme manifests recognised: {len(results)}")
    return results

def extract_palette(data: dict[str, Any]) -> dict[str, str]:
    """
    Return a dict of every key in *data* that is NOT in ``META_KEYS``,
    preserving original key names and converting values to strings.

    This captures all ``*_color`` keys, ``is_dark_mode``, and any other
    non-meta keys present in the manifest.
    """
    palette: dict[str, str] = {}
    for key, value in data.items():
        if key not in META_KEYS:
            palette[key] = str(value) if value is not None else ""
    return palette

def manifest_to_registry_entry(
    yaml_path: Path,
    git_username: str,
    theme_id_dir: str,
    repo_name: str,
) -> dict[str, Any] | None:
    """
    Parse a theme manifest YAML and return a RegistrySoftware-compatible dict,
    or None if the file is not a recognised theme manifest.

    Extra fields added (ignored by Newtonsoft.Json on the C# side):
    * ``palette``        – all non-meta keys from the manifest.
    * ``theme_manifest`` – the full raw manifest dict.
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
    rel_path = yaml_path.relative_to(REPO_ROOT)
    raw_url = build_raw_url(rel_path)
    palette = extract_palette(data)

    entry: dict[str, Any] = {
        "id": entry_id,
        "name": theme_name,
        "names": {"en": theme_name},
        "description": description,
        "descriptions": {"en": description} if description else {},
        "long_description": long_description,
        "tags": [tag],
        "developers": [author],
        "homepage_url": "https://github.com/emeraldsingers/UtauV_Packages",
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
        "palette": palette,
        "theme_manifest": {str(k): (str(v) if v is not None else "") for k, v in data.items()},
    }

    if is_singer_theme:
        singers = str(data.get("singers") or "").strip()
        if singers:
            entry["singers"] = singers

    return entry

def main() -> None:
    print(f"Scanning {REPO_ROOT} for theme manifests …")
    manifests = find_manifests(REPO_ROOT)
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
        rel = yaml_path.relative_to(REPO_ROOT)
        print(f"  [{tag}] {entry_id}  ({entry['name']})  →  {rel}")

    entries.sort(key=lambda e: e.get("name", "").lower())

    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nWrote {len(entries)} entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
