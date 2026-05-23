#!/usr/bin/env python3
"""Validate a WordPress plugin's version is consistent across files and unreleased.

Checks performed:
  1. Main plugin PHP file header `Version:` matches `readme.txt` `Stable tag:`.
  2. Top entry of the `== Changelog ==` section in `readme.txt` matches the same version.
  3. If a `*_VERSION` define() exists in any PHP file, it matches too.
  4. The resolved version does not already exist in the plugin's WP.org SVN `tags/` directory.

Exits 0 on success, non-zero with a human-readable message on failure.
Writes `version=X.Y.Z` to $GITHUB_OUTPUT when running in Actions.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import urllib.error
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


def svn_tag_exists(slug: str, version: str) -> bool:
    url = f"https://plugins.svn.wordpress.org/{slug}/tags/{version}/"
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        print(f"::warning::SVN HEAD for {url} returned HTTP {e.code}; treating as not-existing.", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"::warning::Could not reach WP.org SVN ({e}); skipping tags/ check.", file=sys.stderr)
        return False


def published_stable_tag(slug: str) -> str | None:
    """Read Stable tag from the live trunk/readme.txt on WP.org SVN."""
    url = f"https://plugins.svn.wordpress.org/{slug}/trunk/readme.txt"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # New plugin, nothing published yet.
        print(f"::warning::Fetching {url} returned HTTP {e.code}; skipping published-version check.", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"::warning::Could not reach WP.org SVN ({e}); skipping published-version check.", file=sys.stderr)
        return None
    m = re.search(r"^Stable tag:\s*([0-9][0-9A-Za-z.\-+]*)", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def main() -> None:
    root = Path(os.environ.get("PLUGIN_ROOT", ".")).resolve()
    slug = os.environ.get("PLUGIN_SLUG", "").strip()
    if not slug:
        fail("PLUGIN_SLUG env var is required.")

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

    if svn_tag_exists(slug, version):
        fail(
            f"WP.org SVN already has tags/{version} for '{slug}'. "
            "Bump the version before merging."
        )

    published = published_stable_tag(slug)
    if published is None:
        print("Published Stable tag: <none — first release>")
    else:
        print(f"Published Stable tag: {published}  (currently live on WP.org)")
        if published == version:
            fail(
                f"Version {version} is already the published Stable tag on WP.org for '{slug}'. "
                "Bump the version before merging."
            )
    print(f"OK: version {version} is consistent and not yet released to WP.org.")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")


if __name__ == "__main__":
    main()
