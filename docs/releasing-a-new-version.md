# Releasing a new version of a Hippoo WordPress plugin

This guide walks you through cutting a new release of any plugin wired up to the `hippoo-app/devops-templates` workflows (today: `hippoo` and `hippoo-shippo-integration-for-woocommerce`).

The pipeline does the publish for you. Your job is to:

1. Bump the version in the right places.
2. Open a PR.
3. Get it approved and merged.

Everything after merge — pushing to WP.org SVN, tagging on GitHub, creating the release — happens automatically.

---

## 1. Decide the new version

Use [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`. Bump:

- **PATCH** (`1.2.4 → 1.2.5`) for bug fixes and small tweaks.
- **MINOR** (`1.2.5 → 1.3.0`) for new functionality that doesn't break anything.
- **MAJOR** (`1.3.0 → 2.0.0`) for breaking changes.

The version must not have been released before. The pipeline enforces this by checking for an existing `vX.Y.Z` git tag.

---

## 2. Create a release branch

```bash
git checkout main
git pull
git checkout -b release/1.2.5
```

Branch naming is convention, not enforced — pick whatever you find readable (`release/1.2.5`, `bump-to-1.2.5`, etc.). Just don't push to `main` directly — branch protection won't let you anyway.

---

## 3. Bump the version everywhere

The version must be **identical** in all of these places. This is the only requirement, and the validator will fail your PR if any are out of sync.

### 3.1. Main plugin header — `<plugin-slug>.php`

This is the file at the repo root that has `Plugin Name:` in its header (for example `hippoo.php`, `hippoo-shippo.php`). The header must use the **`/** ... */`** block-comment style, with a leading `* ` on each line:

```php
<?php
/**
 * Plugin Name: Hippoo Shippo Integration for WooCommerce
 * Description: …
 * Version: 1.2.5
 * Author: Hippoo Team
 * ...
 */
```

> If a plugin's header is the older `/* ... */` style with no leading `*` on each line, normalize it the first time you touch it. The validator only accepts the `/**` style.

### 3.2. `readme.txt` Stable tag

Near the top of `readme.txt`:

```
Stable tag: 1.2.5
```

### 3.3. `readme.txt` changelog

The top entry of the `== Changelog ==` section must be the new version. Either of these formats works:

```
== Changelog ==

= 1.2.5 =
* Fixed X.
* Added Y.

= 1.2.4 =
…
```

or bullet style:

```
== Changelog ==

* 1.2.5 – Fixed X, added Y.
* 1.2.4 – …
```

Always **add** the new entry on top; never edit history.

### 3.4. PHP version constants (if your plugin has any)

If your plugin defines a constant like `MYPLUGIN_VERSION`, `HIPPOO_VERSION`, etc., the validator will look for them too. The convention is **all-uppercase**:

```php
define( 'HIPPOO_VERSION', '1.2.5' );
```

Lowercase variants (`hippshipp_version` etc.) are not checked. If your plugin uses one of those *and* you want it synced, rename it to uppercase first.

### 3.5. Sanity-check locally (optional)

You can run the same validator the CI runs:

```bash
git clone https://github.com/hippoo-app/devops-templates.git /tmp/devops-templates
cd /path/to/your-plugin
PLUGIN_SLUG=hippoo-shippo-integration-for-woocommerce \
  python3 /tmp/devops-templates/scripts/check_version.py
```

It prints exactly what each file says and exits non-zero if anything's off.

---

## 4. Commit and push

```bash
git add -A
git commit -m "Release v1.2.5"
git push -u origin release/1.2.5
```

---

## 5. Open a Pull Request to `main`

Either via the link printed by `git push`, or:

```bash
gh pr create --base main --title "Release v1.2.5"
```

In the PR description, paste the changelog entries you added so reviewers can read them. A minimal body:

```
## Changes
- Fixed X.
- Added Y.

## Release notes
This bumps 1.2.4 → 1.2.5.
```

---

## 6. Watch the PR check

GitHub Actions runs **`validate / validate`** on every PR. It checks that:

- The version is consistent across `<plugin>.php` header, `readme.txt` Stable tag, the top `== Changelog ==` entry, and any uppercase `*_VERSION` PHP constants.
- No git tag `vX.Y.Z` exists yet for the proposed version.

If it fails, the error in the Actions log will name the exact file and value. Fix locally, commit, push — the check re-runs.

---

## 7. Get a review

Branch protection requires **one approving review** before merge. Any org member with write access can approve. You can't self-approve a PR you authored; ask a teammate.

---

## 8. Merge

Use the **Merge pull request** button on GitHub. Either "Create a merge commit" or "Squash and merge" is fine; pick the one your team prefers.

That's it. Don't tag the release yourself — the pipeline does it.

---

## 9. What happens after merge

The `release.yml` workflow on `main` fires automatically and:

1. Re-runs the validator (same checks as the PR).
2. Stages the plugin files (excludes `.git`, `.github`, `.gitignore`, `node_modules`, etc.).
3. Pushes the contents to WP.org SVN `trunk/`.
4. Copies trunk to WP.org SVN `tags/<version>/`.
5. If you have a `.wordpress-org/` directory with banner/icon/screenshots, pushes those under SVN `/assets/`.
6. Creates a `vX.Y.Z` git tag and a matching GitHub release pointing at the merge commit.

You can watch it from the **Actions** tab of the plugin repo. Typical runtime is 30–60 seconds.

A successful run means **the new version is live on WordPress.org**, usually visible within a few minutes at:

```
https://wordpress.org/plugins/<plugin-slug>/
```

---

## 10. If something goes wrong after merge

The most common cause is the deploy half failing while validate passed (rare — usually transient SVN flakiness or an expired SVN credential). To retry:

```bash
# Push an empty commit on main to re-trigger the release workflow.
git checkout main
git pull
git commit --allow-empty -m "ci: retry release for vX.Y.Z"
git push
```

The validator will pass (the version is still consistent) and the deploy will retry. If the issue is structural — wrong credentials, WP.org outage, etc. — ping the DevOps owner; they may need to update the org secrets.

If you need to **un-release** a version (it shouldn't have shipped), contact the DevOps owner. WP.org SVN tags can't be deleted via the pipeline; this is a manual operation.

---

## Cheat sheet

```bash
# 0. fresh main
git checkout main && git pull

# 1. branch
git checkout -b release/X.Y.Z

# 2. bump in:
#    <plugin>.php           — Version: X.Y.Z (in /** */ header)
#    readme.txt             — Stable tag: X.Y.Z
#    readme.txt             — top entry of == Changelog == is X.Y.Z
#    any *_VERSION constant — '<X.Y.Z>'

# 3. (optional) local check
PLUGIN_SLUG=<slug> python3 /path/to/devops-templates/scripts/check_version.py

# 4. push & PR
git add -A && git commit -m "Release vX.Y.Z" && git push -u origin HEAD
gh pr create --base main --title "Release vX.Y.Z"

# 5. wait for green check, get a review, merge.
# 6. watch the Actions tab — it publishes to WP.org and tags the repo.
```
