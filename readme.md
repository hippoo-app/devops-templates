# devops-templates

Reusable GitHub Actions workflows for `hippoo-app` WordPress plugins.

## What's here

- `.github/workflows/validate-plugin.yml` — runs on every PR via the caller repo. Verifies the plugin version is consistent across `*.php` header, `readme.txt` `Stable tag:`, the top `== Changelog ==` entry, and any `*_VERSION` PHP `define()`. Also checks the version has not already been published as a WP.org SVN tag.
- `.github/workflows/deploy-to-wporg.yml` — runs on push to `main` in the caller repo. Re-validates, then publishes to `trunk` and `tags/<version>` on `plugins.svn.wordpress.org`. Creates a matching `vX.Y.Z` GitHub release. The PR-approval requirement on `main` is the single human gate.
- `scripts/check_version.py` — the validator, callable locally too: `PLUGIN_SLUG=hippoo python3 scripts/check_version.py`

## How a plugin repo uses these

Add **two tiny caller workflows** to the plugin repo (see `hippoo` and `hippoo-shippo-integration-for-woocommerce` for live examples):

```yaml
# .github/workflows/pr.yml
on: { pull_request: { branches: [main] } }
jobs:
  validate:
    uses: hippoo-app/devops-templates/.github/workflows/validate-plugin.yml@main
    with:
      plugin-slug: my-plugin-slug
```

```yaml
# .github/workflows/release.yml
on: { push: { branches: [main] } }
jobs:
  release:
    uses: hippoo-app/devops-templates/.github/workflows/deploy-to-wporg.yml@main
    with:
      plugin-slug: my-plugin-slug
    secrets:
      SVN_USERNAME: ${{ secrets.WPORG_SVN_USERNAME }}
      SVN_PASSWORD: ${{ secrets.WPORG_SVN_PASSWORD }}
```

## Secrets

Stored as organization-level secrets and selected per repo:

- `WPORG_SVN_USERNAME_HIPPOOO` / `WPORG_SVN_PASSWORD_HIPPOOO` — for plugins published by the `hippooo` WP.org account (hippoo, hippoo-ticket, hippoo-notification, hippoo-popup, hippoo-shippo-integration-for-woocommerce).
- `WPORG_SVN_USERNAME_HIPPOOSUPPORT` / `WPORG_SVN_PASSWORD_HIPPOOSUPPORT` — for plugins published by the `hippoosupport` account (hippoo-auth).

Each plugin repo's `release.yml` wires the right pair into `SVN_USERNAME` / `SVN_PASSWORD`.

## Release flow

1. Developer opens a PR bumping the version in `<plugin>.php`, `readme.txt` (Stable tag + changelog).
2. PR check runs `validate-plugin.yml` — must be green.
3. PR is reviewed and approved (the single human gate).
4. Merge to `main` triggers `deploy-to-wporg.yml`, which re-validates and pushes `trunk` and `tags/<version>` to WP.org SVN and tags `vX.Y.Z` on GitHub.
