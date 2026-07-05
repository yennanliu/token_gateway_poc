# Follow-ups & Known Issues

Non-blocking items to revisit. Nothing here breaks the build or tests today —
each is a "fix later" note with enough context to act on directly.

> Compiled: 2026-07-05

---

## CI

### 1. CI badge in README
- **What:** A CI status badge was added to `README.md`:
  `[![CI](https://github.com/yennanliu/token_gateway_poc/actions/workflows/ci.yml/badge.svg)](…)`.
- **Status:** Working — both CI jobs pass on GitHub.
- **Note:** If the repo is renamed or moved, update the badge URL (owner/repo and
  workflow filename must match `.github/workflows/ci.yml`).

### 2. GitHub Actions — Node 20 deprecation warning
- **What:** CI runs emit a non-blocking annotation:
  > Node.js 20 is deprecated. The following actions target Node.js 20 but are
  > being forced to run on Node.js 24: `actions/checkout@v4`,
  > `astral-sh/setup-uv@v6`.
  Ref: <https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/>
- **Impact:** None today — the runner auto-upgrades these actions to Node 24, so
  jobs still pass. It's a warning, not a failure.
- **Fix later:** Bump the action versions once newer (Node 24-targeting) releases
  are available, in `.github/workflows/ci.yml` (both the `test` and
  `migrations-postgres` jobs):
  - `actions/checkout@v4` → newer major (e.g. `@v5`) when it targets Node 24.
  - `astral-sh/setup-uv@v6` → newer major when it targets Node 24.
- **Verify after bump:** push and confirm both CI jobs are green and the
  annotation is gone.

---

## Other deferred items (from earlier phases)

These were intentionally left as graceful fallbacks / stubs; documented here so
they aren't forgotten.

- **Redis rate limiting** is wired (`REDIS_URL`) but the default remains the
  in-memory token bucket; the Redis path is process-shared fixed-window. For
  true multi-instance limiting, validate the Redis backend under load.
- **Stripe payments** support real Checkout + signed webhooks, but production
  needs real keys, a registered webhook endpoint, and success/cancel URLs set in
  env (`STRIPE_*`). Mock mode (immediate credit) is the default with no key.
- **Git history** still contains the original pre-rebrand references in older
  commits (current tree is clean). Rewriting history (`git filter-repo` +
  force-push) is available if the origin must be scrubbed from history too.
