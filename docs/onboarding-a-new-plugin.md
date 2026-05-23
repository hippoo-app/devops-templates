# Onboarding a new plugin to the automated release pipeline

Operator runbook. Use this when adding a new WordPress plugin under `hippoo-app` to the automated release flow that's already in place for `hippoo` and `hippoo-shippo-integration-for-woocommerce`.

If you're a developer cutting a release of an *already-onboarded* plugin, you want [releasing-a-new-version.md](releasing-a-new-version.md) instead.

---

## What you'll set up

Per plugin, the end state is:

| Component | Where it lives |
|---|---|
| Plugin source code | `github.com/hippoo-app/<slug>` (public repo) |
| PR-time validator workflow | `<slug>`/`.github/workflows/pr.yml` (3-line caller) |
| Post-merge release workflow | `<slug>`/`.github/workflows/release.yml` (5-line caller) |
| Branch protection (1 review on `main`) | repo setting |
| Baseline tag `vX.Y.Z` of the currently-published version | git tag on the repo |
| SVN credentials | shared org secrets, selected onto this repo |

The actual release logic stays in `devops-templates` — caller repos only carry tiny references.

---

## Pre-flight — verify the org is healthy

These were one-time setup steps; you shouldn't have to redo them, but if Actions don't fire for a new plugin, this is the checklist.

```bash
# 1. gh CLI is authenticated with the scopes needed for everything below.
gh auth status
# Required scopes: admin:org, repo, workflow
# If missing:
#   gh auth refresh -h github.com -s admin:org,repo,workflow

# 2. Org-level Actions policy allows running anything.
gh api orgs/hippoo-app/actions/permissions
# Expect: {"enabled_repositories":"all","allowed_actions":"all", ...}

# 3. devops-templates is public (caller repos must be able to load reusable workflows).
gh api repos/hippoo-app/devops-templates --jq '.visibility'
# Expect: "public"

# 4. Org billing has a payment method on file.
# Visit: https://github.com/organizations/hippoo-app/billing/payment_information
# Even though public-repo Actions minutes are free, GitHub will not
# allocate hosted runners without a card on file. If runs sit "queued"
# forever after onboarding, this is almost always the cause.
```

---

## Step 1 — Pick the slug and create the GitHub repo

The slug must exactly match the WP.org SVN repo name. For example, if the WP.org SVN URL is `https://plugins.svn.wordpress.org/hippoo-popup/`, the GitHub repo must be named `hippoo-popup`.

```bash
slug=hippoo-popup           # change this

gh repo create hippoo-app/$slug \
  --public \
  --description "Hippoo $slug plugin — published to WordPress.org" \
  --add-readme
```

**Important:** create the repo as `--public`. The org is on the GitHub Free plan, where private repos don't get Actions or branch protection. Public is also fine because the source ends up on WP.org SVN openly anyway.

If the repo already exists and is private, flip it:

```bash
gh api -X PATCH repos/hippoo-app/$slug -f visibility=public
```

---

## Step 2 — Map the plugin to the right SVN account

WordPress.org credentials are scoped per-plugin. Two accounts publish hippoo-app plugins:

| WP.org account | Plugins | Org secrets to reference |
|---|---|---|
| `hippooo` | `hippoo`, `hippoo-popup`, `hippoo-ticket`, `hippoo-notification`, `hippoo-shippo-integration-for-woocommerce` | `WPORG_SVN_USERNAME_HIPPOOO` / `WPORG_SVN_PASSWORD_HIPPOOO` |
| `hippoosupport` | `hippoo-auth` | `WPORG_SVN_USERNAME_HIPPOOSUPPORT` / `WPORG_SVN_PASSWORD_HIPPOOSUPPORT` |

If you're onboarding the first plugin owned by `hippoosupport` (or any new account), create that secret pair at the org first:

```bash
gh secret set WPORG_SVN_USERNAME_HIPPOOSUPPORT --org hippoo-app --visibility selected --body 'hippoosupport'
gh secret set WPORG_SVN_PASSWORD_HIPPOOSUPPORT --org hippoo-app --visibility selected --body '<password>'
```

Then, regardless of whether the secrets already existed, **add the new repo to their selected list** so the workflow can read them:

```bash
# Append $slug to the list of repos that can read the secret.
existing=$(gh api orgs/hippoo-app/actions/secrets/WPORG_SVN_USERNAME_HIPPOOO/repositories \
  --jq '[.repositories[].id] | @json')
new_id=$(gh api repos/hippoo-app/$slug --jq '.id')
ids=$(python3 -c "import json,sys; e=json.loads('$existing'); e.append($new_id); print(','.join(str(x) for x in sorted(set(e))))")
gh api -X PUT "orgs/hippoo-app/actions/secrets/WPORG_SVN_USERNAME_HIPPOOO/repositories" -f "selected_repository_ids[]=$ids"
# Repeat for WPORG_SVN_PASSWORD_HIPPOOO.
```

(Or do it via the UI at `https://github.com/organizations/hippoo-app/settings/secrets/actions` — click the secret, then "Update repositories".)

---

## Step 3 — Seed the repo with the plugin source

Three possible sources, in order of preference:

### 3a. Pull from WP.org SVN trunk (cleanest start)

Best when you want the currently-published version as the baseline. SVN client isn't installed locally; do the checkout on the dev box, then rsync down:

```bash
# Replace $slug with the plugin slug.
ssh ak-host-do "
  set -e
  d=\$(mktemp -d)
  cd \$d
  svn checkout https://plugins.svn.wordpress.org/$slug/trunk/ trunk
  echo TMPDIR=\$d
" | tee /tmp/seed.log

tmpdir=$(grep '^TMPDIR=' /tmp/seed.log | cut -d= -f2)
rsync -av --exclude='.svn' --exclude='.svn/**' \
  "ak-host-do:$tmpdir/trunk/" /Users/amir/workspace/code/github.com/hippoo-app/$slug/
ssh ak-host-do "rm -rf $tmpdir"
```

### 3b. Rsync from the dev server filesystem

When the source on the server is the authoritative copy (e.g. it's ahead of WP.org):

```bash
# Confirm the path first — it varies. Recent paths:
ssh ak-host-do "find /var/www -maxdepth 6 -type d -name '$slug' 2>/dev/null"

# Then rsync down. Adjust the path.
rsync -av --delete --exclude='.git' --exclude='.git/**' \
  "ak-host-do:/var/www/html/hippoo.app/public_html/wp-content/plugins/$slug/" \
  /Users/amir/workspace/code/github.com/hippoo-app/$slug/
```

`--delete` mirrors the source. If the repo had a starter `README.md` or `LICENSE` you want to keep, restore them with `git checkout README.md LICENSE` after.

### 3c. From a local copy

If the user has the latest source on their laptop:

```bash
rsync -av --exclude='.git' --exclude='.git/**' \
  "/path/to/source/" \
  /Users/amir/workspace/code/github.com/hippoo-app/$slug/
```

### After seeding — always check the plugin header style

The validator requires the standard `/** ... */` style with a leading `* ` on each header line. Many older Hippoo plugins use the bare `/* ... */` style. If yours does, normalize it now (one-time per plugin):

```diff
-<?php
-/*
-Plugin Name: ...
-Plugin URI: ...
-Version: 1.2.5
-...
-*/
+<?php
+/**
+ * Plugin Name: ...
+ * Plugin URI: ...
+ * Version: 1.2.5
+ * ...
+ */
```

---

## Step 4 — Add the two caller workflows + .gitignore

Both files are identical across plugins except for the slug and the SVN secrets pair.

`.github/workflows/pr.yml`:

```yaml
name: PR checks

on:
  pull_request:
    branches: [main]

jobs:
  validate:
    uses: hippoo-app/devops-templates/.github/workflows/validate-plugin.yml@main
    with:
      plugin-slug: <slug>
```

`.github/workflows/release.yml`:

```yaml
name: Release to WordPress.org

on:
  push:
    branches: [main]

jobs:
  release:
    uses: hippoo-app/devops-templates/.github/workflows/deploy-to-wporg.yml@main
    with:
      plugin-slug: <slug>
    secrets:
      SVN_USERNAME: ${{ secrets.WPORG_SVN_USERNAME_HIPPOOO }}      # or _HIPPOOSUPPORT
      SVN_PASSWORD: ${{ secrets.WPORG_SVN_PASSWORD_HIPPOOO }}      # or _HIPPOOSUPPORT
```

`.gitignore`:

```
.DS_Store
node_modules/
vendor/
*.log
.idea/
.vscode/
```

---

## Step 5 — Validate locally before pushing

```bash
cd /Users/amir/workspace/code/github.com/hippoo-app/$slug
PLUGIN_SLUG=$slug python3 ../devops-templates/scripts/check_version.py
```

Expect:

```
Main file:          <slug>.php  -> Version: X.Y.Z
readme.txt:         Stable tag: X.Y.Z
readme.txt:         top changelog entry: X.Y.Z
Git tag vX.Y.Z: not yet present.
OK: version X.Y.Z is consistent and unreleased.
```

If it fails, fix the source (not the validator). The validator is intentionally strict; treat its errors as the spec.

> Note: it'll say "not yet present" because the repo has no tags yet. We're about to create one in Step 6 to mark the *currently-published* version as already-out.

---

## Step 6 — Push the baseline + create the "already published" tag

This is the trickiest part. The release workflow will fire as soon as anything lands on `main`. To prevent it from re-publishing the version already live on WP.org, we tag that version *before* the first push to `main`.

```bash
cd /Users/amir/workspace/code/github.com/hippoo-app/$slug

# Commit and create the tag locally.
git add -A
git -c user.email=adezfulian@gmail.com -c user.name=amirdez commit -m "Seed from WP.org SVN trunk (vX.Y.Z) and add CI workflows

- Plugin source from <where you got it>.
- Header normalized to /** ... */ style.
- .github/workflows/pr.yml: calls devops-templates validate-plugin on PR.
- .github/workflows/release.yml: calls devops-templates deploy-to-wporg on push to main."

git -c user.email=adezfulian@gmail.com -c user.name=amirdez \
  tag -a vX.Y.Z -m "WP.org SVN trunk baseline (already published)"

# Push the tag FIRST so the validator sees it before main lands.
git push origin vX.Y.Z

# Then push main. The release workflow fires; validate sees the tag and blocks deploy.
git push origin main
```

Verify the post-push run failed at validate (not deploy):

```bash
gh run list -R hippoo-app/$slug -L 2
# Expect the topmost to be "failure" with workflow "Release to WordPress.org".

# Confirm the failure is "Git tag vX.Y.Z already exists":
gh run view <run-id> -R hippoo-app/$slug --log | grep -i "Git tag"
```

That failure is **good** — it's the safeguard working. If validate instead passed and deploy ran, the tag step was skipped; investigate before proceeding.

---

## Step 7 — Enable branch protection

```bash
gh api -X PUT repos/hippoo-app/$slug/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": false
}
JSON
```

After this, future direct pushes to `main` are blocked. PRs require one approving review.

> If you need to push directly to `main` for a fix (rare), lift protection, push, restore: `gh api -X DELETE repos/hippoo-app/$slug/branches/main/protection` → push → re-PUT the JSON above.

---

## Step 8 — End-to-end smoke test (optional but recommended)

The smoothest test is a real release of the next version. Bump locally, open a PR, follow [releasing-a-new-version.md](releasing-a-new-version.md). On a successful run you should see:

- PR check `validate / validate`: ✅
- Post-merge `release / validate`: ✅
- Post-merge `release / deploy`: ✅
- `tags/X.Y.Z/` appears at `https://plugins.svn.wordpress.org/<slug>/tags/`
- `Stable tag:` in `trunk/readme.txt` matches the new version
- A `vX.Y.Z` GitHub release at `https://github.com/hippoo-app/<slug>/releases`
- The plugin's WP.org page shows the new version within a few minutes

If you don't want to release for real yet, you can verify the wiring with a no-op PR (e.g. a comment-only change to `<slug>.php`); the validator will pass since version is unchanged, and deploy won't fire (nothing was merged).

---

## Common gotchas — what went wrong during the first onboarding

These bit us during initial setup. Watch for them.

| Symptom | Cause | Fix |
|---|---|---|
| Pushes register but **zero workflow runs appear** | Org's billing has no payment method | Add a card at `org/billing/payment_information`. Free for public-repo minutes. |
| Pushes register but **zero workflow runs appear** | Repo is private on Free plan | Make repo public (`gh api -X PATCH repos/.../$slug -f visibility=public`). |
| `actions/checkout` in the reusable workflow fails with `could not read Username for 'https://github.com'` | Reusable workflow called with explicit `secrets:` block loses caller-repo write scope on the auto-generated `GITHUB_TOKEN` | Already fixed in `devops-templates`: the reusable workflows declare `permissions:` and pass `token: ${{ github.token }}` explicitly. If this resurfaces after a refactor, re-check both `validate-plugin.yml` and `deploy-to-wporg.yml`. |
| `10up/action-wordpress-plugin-deploy` errors `svn: E155010: Path '.../tags/refs/heads' is not a directory` | Action fell back to parsing `GITHUB_REF` because `VERSION` env var wasn't set | Already fixed: `deploy-to-wporg.yml` passes `VERSION: ${{ needs.validate.outputs.version }}` explicitly. |
| PR validate passes, post-merge deploy says **"version 1.x.y already published"** | Forgot to create the baseline `vX.Y.Z` tag before the first push to `main` | Create the tag retroactively on the merge commit, force-push it, retry the release via empty commit on main. |
| Pre-existing repo has plugin file with `/*` (not `/**`) header | Validator is strict on header style | Normalize the file (one-time edit). Documented in Step 3. |
| Reusable workflow call fails with **`access denied to hippoo-app/devops-templates`** | `devops-templates` is private and the caller repo doesn't have access | Either make `devops-templates` public (current state), or `gh api -X PUT repos/hippoo-app/devops-templates/actions/permissions/access -f access_level=organization`. |
| Can't enable branch protection — **"Upgrade to GitHub Pro or make this repository public"** | Repo is private on Free plan | Flip repo to public. |
| Force-push to `main` rejected — **"protected branch hook declined"** | Branch protection blocks force-push | Lift protection (`gh api -X DELETE .../branches/main/protection`), push, re-PUT the protection JSON. |

---

## Credentials hygiene

- SVN credentials live only in GitHub org secrets. Never commit them; never paste them in chat with the operator (rotate immediately if you do).
- Rotate WP.org passwords periodically — and **always** after they've appeared anywhere outside the GitHub secrets UI.
- After a rotation: `gh secret set WPORG_SVN_PASSWORD_HIPPOOO --org hippoo-app --visibility selected --body '<new password>'` — the existing repo selection is preserved.

---

## Map of moving pieces (mental model)

```
                   ┌──────────────────────────────┐
                   │  hippoo-app/devops-templates │ ← reusable workflows + validator script
                   │   .github/workflows/         │   live here. Public so any caller can use.
                   │     validate-plugin.yml      │
                   │     deploy-to-wporg.yml      │
                   │   scripts/                   │
                   │     check_version.py         │
                   │   docs/                      │
                   └─────────┬────────────────────┘
                             │ uses: ...@main
            ┌────────────────┼────────────────────────┐
            │                │                        │
   ┌────────▼──────┐   ┌─────▼──────────────────┐   ┌─▼──────────────┐
   │ hippoo-app/   │   │ hippoo-app/            │   │ hippoo-app/    │
   │   hippoo      │   │   hippoo-shippo-...    │   │   <future-...> │
   │  pr.yml       │   │  pr.yml                │   │  pr.yml        │ ← per-plugin
   │  release.yml  │   │  release.yml           │   │  release.yml   │   ~10 lines each
   └───────────────┘   └────────────────────────┘   └────────────────┘
            │                │                        │
            └────────────────┼────────────────────────┘
                             │ push to trunk + tags/<v>
                   ┌─────────▼────────────────────┐
                   │  plugins.svn.wordpress.org/  │
                   │     hippoo, hippoo-shippo-...│
                   └──────────────────────────────┘
```

---

## File reference

If anything in the pipeline is broken, the four files that matter:

- [.github/workflows/validate-plugin.yml](../.github/workflows/validate-plugin.yml) — PR-time consistency + uniqueness checks.
- [.github/workflows/deploy-to-wporg.yml](../.github/workflows/deploy-to-wporg.yml) — post-merge publish.
- [scripts/check_version.py](../scripts/check_version.py) — validator implementation.
- [docs/releasing-a-new-version.md](releasing-a-new-version.md) — developer-facing instructions.
