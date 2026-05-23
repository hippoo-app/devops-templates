#!/usr/bin/env python3
"""Validate a WordPress plugin's version is consistent across files and unreleased.

Checks performed:
  1. Main plugin PHP file header `Version:` matches `readme.txt` `Stable tag:`.
  2. Top entry of the `== Changelog ==` section in `readme.txt` matches the same version.
  3. If a `*_VERSION` define() exists in any PHP file, it matches too.
  4. No git tag `vX.Y.Z` already exists for the resolved version (git tags are the
     source of truth for what has been published).

Exits 0 on success, non-zero with a human-readable message on failure.
Writes `version=X.Y.Z` to $GITHUB_OUTPUT when running in Actions.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def fail(msg: str) -> "None":
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def find_main_plugin_file(root: Path) -> Path:
    for php in sorted(root.glob("*.php")):
        text = php.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*\*\s*Plugin Name:", text, re.MULTILINE):
            return php
    fail("Could not locate the main plugin PHP file (no top-level *.php has a 'Plugin Name:' header).")


def header_version(php_file: Path) -> str:
    text = php_file.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-+]*)", text, re.MULTILINE)
    if not m:
        fail(f"No 'Version:' header found in {php_file.name}.")
    return m.group(1).strip()


def stable_tag(readme: Path) -> str:
    text = readme.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^Stable tag:\s*([0-9][0-9A-Za-z.\-+]*)", text, re.MULTILINE)
    if not m:
        fail("No 'Stable tag:' line found in readme.txt.")
    return m.group(1).strip()


def top_changelog_version(readme: Path) -> str:
    text = readme.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"==\s*Changelog\s*==\s*(.*?)(?:\n==\s|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        fail("No '== Changelog ==' section found in readme.txt.")
    block = m.group(1)
    # Accept either '= 1.2.3 =' (heading style) or '* 1.2.3 ...' (bullet style).
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        mm = re.match(r"=\s*([0-9][0-9A-Za-z.\-+]*)\s*=", line)
        if mm:
            return mm.group(1)
        mm = re.match(r"\*\s*([0-9][0-9A-Za-z.\-+]*)\b", line)
        if mm:
            return mm.group(1)
    fail("Could not parse any version entry inside '== Changelog =='.")


def php_constant_versions(root: Path) -> list[tuple[Path, str, str]]:
    pat = re.compile(
        r"""define\s*\(\s*['"]([A-Z][A-Z0-9_]*_VERSION)['"]\s*,\s*['"]([0-9][0-9A-Za-z.\-+]*)['"]""",
    )
    found: list[tuple[Path, str, str]] = []
    for php in root.rglob("*.php"):
        # Skip vendor / node_modules dumps.
        parts = set(php.parts)
        if "vendor" in parts or "node_modules" in parts:
            continue
        try:
            text = php.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(text):
            found.append((php, m.group(1), m.group(2)))
    return found


def git_tag_exists(root: Path, tag: str) -> bool:
    """True iff `tag` exists in the git repo containing `root`.

    Fetches tags from origin first so PR runs see tags created by main-branch
    deploys. Falls back to local-only lookup if the network fetch fails.
    """
    try:
        subprocess.run(
            ["git", "fetch", "--tags", "--quiet", "origin"],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = subprocess.run(
            ["git", "tag", "--list", tag],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"::warning::Could not list git tags ({e}); skipping git-tag uniqueness check.", file=sys.stderr)
        return False
    return tag in result.stdout.splitlines()


def main() -> None:
    root = Path(os.environ.get("PLUGIN_ROOT", ".")).resolve()
    slug = os.environ.get("PLUGIN_SLUG", "").strip() or root.name

    main_php = find_main_plugin_file(root)
    readme = root / "readme.txt"
    if not readme.exists():
        fail("readme.txt not found at plugin root.")

    v_header = header_version(main_php)
    v_stable = stable_tag(readme)
    v_changelog = top_changelog_version(readme)

    print(f"Plugin slug:        {slug}")
    print(f"Main file:          {main_php.name}  -> Version: {v_header}")
    print(f"readme.txt:         Stable tag: {v_stable}")
    print(f"readme.txt:         top changelog entry: {v_changelog}")

    if not (v_header == v_stable == v_changelog):
        fail(
            "Version mismatch — "
            f"{main_php.name} header={v_header}, readme Stable tag={v_stable}, "
            f"changelog top={v_changelog}. All three must match."
        )

    constants = php_constant_versions(root)
    if constants:
        bad = [(p, name, val) for (p, name, val) in constants if val != v_header]
        for p, name, val in constants:
            rel = p.relative_to(root)
            print(f"PHP constant:       {name} in {rel} = {val}")
        if bad:
            lines = ", ".join(f"{name} in {p.relative_to(root)} = {val}" for p, name, val in bad)
            fail(f"PHP version constant(s) do not match {v_header}: {lines}")

    version = v_header

    tag = f"v{version}"
    if git_tag_exists(root, tag):
        fail(
            f"Git tag {tag} already exists — that version has been published. "
            "Bump the version before merging."
        )
    print(f"Git tag {tag}: not yet present.")
    print(f"OK: version {version} is consistent and unreleased.")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")


if __name__ == "__main__":
    main()
