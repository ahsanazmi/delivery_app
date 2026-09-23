# Phase 40 — Production Payment Readiness

## Scope
Verify, before production: Razorpay production credentials, webhook
URL, webhook secret, HTTPS, CORS, environment variables, database
migrations, logging, monitoring, error handling, refund handling,
payment reconciliation. Ensure: test credentials are never used in
production, production secrets are never committed, debug mode is
disabled, HTTPS is used, and the webhook endpoint is protected by
signature verification.

## Method
A dedicated Explore subagent ran a read-only, evidence-cited audit
against all twelve items (git history, `config.py`, `main.py`,
logging, migrations, `.env.example`), reporting exact file:line
citations rather than assumptions. I independently re-verified the
one critical finding myself before acting on it, then fixed every
genuine gap found. Nothing here was fixed speculatively — every
change below traces to a specific, cited finding.

## CRITICAL — a real credential was committed to git

`rzp-test-key.csv` (repo root) was tracked by git and contained, in
plaintext, a real, working Razorpay TEST-mode key/secret pair
(`rzp_test_Tf3dhqj9WrIRwY` / its secret). `.gitignore` lists this
exact filename with a comment calling it "a real, working credential
pair" — but the file had already been committed (in `c07d240d1`,
"payment_integration") *before* that ignore rule was added, so the
rule never took effect (`git check-ignore -v rzp-test-key.csv`
confirmed: not ignored). `docs/payments/phase-5-payment-api-design.md`
also quoted the same `key_id` in plaintext and incorrectly claimed the
CSV was gitignored.

**What this phase did about it:**
- `git rm --cached rzp-test-key.csv` (staged, not committed — the
  user decides when to commit this) and deleted the local copy.
- Redacted the real key value from `phase-5-payment-api-design.md`
  and corrected its false "gitignored" claim, with an explicit note
  that the key remains recoverable from git history at `c07d240d1`.

**What this phase could NOT do, and still needs a human:**
- **The key/secret pair must be rotated in the Razorpay dashboard.**
  Removing the file from the current tree does not un-leak it — it's
  permanently recoverable from git history regardless. This
  environment has no Razorpay dashboard access, so this step could
  not be performed here.
- Whether to rewrite git history to scrub the secret from past
  commits entirely (vs. accepting that the *value* is dead the moment
  it's rotated, so a scrub is defense-in-depth rather than strictly
  required) is a decision with real consequences (force-push, every
  clone/fork needs to re-sync) — left to the user to decide, not
  taken automatically.
- Only test-mode credentials were involved here; no live/production
  key was found anywhere in the tracked tree or its history.

Since it's directly relevant to this same finding: `.gitignore`
already correctly excludes `.env`/`.env.*` (with a `!.env.example`
carve-out) at both repo root and `backend/`, and no `.env` file
itself is currently tracked anywhere. `customer-mobile/.env.development`
and `rider-mobile/.env.development` are tracked (a real anti-pattern —
any `.env.development` should never be tracked, matching the repo's
own `.gitignore` philosophy for `.env`), but their actual contents
were checked directly and contain nothing but a blank
`EXPO_PUBLIC_API_BASE_URL` with an explanatory comment — no secret of
any kind. Left as tracked rather than removed in this phase, since
they're genuinely empty and removing them wasn't a finding this
audit's scope named as an "Ensure" item the way the CSV secret was.

## Fixed: no guard against Razorpay test-mode credentials in production

`config.py`'s `model_post_init()` already had Phase 31's fail-fast
guards for `JWT_SECRET_KEY` (rejects the placeholder or anything under
32 chars) and `DEBUG` (must be false) when `ENVIRONMENT=production` —
but nothing extended that same protection to Razorpay. Added, in the
same style:
- `RAZORPAY_KEY_ID` starting with `rzp_test_` (Razorpay's own
  documented test-key prefix) now refuses to boot in production —
  money would appear to move but never actually settle.
- `RAZORPAY_KEY_ID` set (online payments enabled) with
  `RAZORPAY_WEBHOOK_SECRET` empty also refuses to boot — a captured
  payment could only ever be confirmed asynchronously via a signed
  webhook, so this half-configured state would silently strand real
  payments in PENDING/PROCESSING forever. A fully unconfigured
  Razorpay (COD-only production deployment) remains a legitimate,
  unguarded choice — only the *half*-configured state is an error.

## Fixed: interactive API docs were unconditionally public

`FastAPI(...)` never varied `openapi_url`/`docs_url`/`redoc_url` by
environment — Swagger UI and ReDoc, which enumerate every route and
let anyone "Try it out" against the live API, would have been
reachable in production with no gate at all. Fixed: a new
`_should_enable_docs(environment)` helper (`app/main.py`) returns
`False` only for `ENVIRONMENT=production`; `openapi_url=None` when
disabled also disables `docs_url`/`redoc_url` automatically (both are
generated from that same schema). The root `/` endpoint's own
`"docs": "/docs"` claim is now conditional too, so it doesn't
advertise a route that no longer exists in production.

## Fixed: no monitoring/health endpoint existed at all

Nothing — no `/health`, `/healthz`, `/ping`, no APM/error-tracking SDK
anywhere in the codebase. A new `GET /health` (unauthenticated, standard
practice — it reveals nothing sensitive) does a real database round
trip (`SELECT 1` via its own, independently-opened `SessionLocal()`,
not the request-scoped dependency) and returns `503` if the database
is unreachable, `200 {"status": "ok"}` otherwise — the one dependency
actually worth confirming for a load balancer/orchestrator. An
error-tracking SDK (Sentry or similar) was deliberately **not** added:
that's a real new piece of infrastructure (new dependency, external
account, budget decision) the phase's own "do not introduce
unnecessary infrastructure for MVP" instruction rules out adding
unilaterally — flagged as a recommendation for the user to decide on,
not implemented.

## Reviewed — already correct, no change needed

- **Webhook signature verification**: unchanged and already correct —
  re-confirmed by this audit, not re-litigated. Every webhook request
  is HMAC-verified against `RAZORPAY_WEBHOOK_SECRET` before any
  parsing happens at all (proven across Phases 17/18/31/38, including
  a real-HTTP malformed-but-signed-body test added in Phase 38).
- **CORS**: no wildcard `allow_origins`; driven entirely by the
  `CORS_ORIGINS` env var with a safe, localhost-only default. Not
  given a production-time hard-fail guard (unlike JWT/DEBUG/Razorpay
  above) because the *unsafe* direction here is a silent security
  hole, while the *unsafe* default (localhost-only) fails loudly and
  obviously the moment a real frontend tries to call the API — the
  asymmetry that makes the other three worth a hard boot-time guard
  doesn't apply the same way here.
- **HTTPS**: the backend has no code-level HTTPS opinion (no
  `HTTPSRedirectMiddleware`, no secure-cookie flags) and relies
  entirely on the deployment layer (reverse proxy/load balancer) for
  TLS termination — a standard, correct split of responsibility for
  a backend that sits behind infrastructure it doesn't control, not a
  gap to fix in application code.
- **Logging**: no signature, key secret, webhook secret, full payload,
  or JWT is ever logged anywhere in the payment code path (grepped
  every `logger.*` call in `app/services/payment/` and the payment
  endpoints) — `payment_service.py` even has an explicit
  "never logs the signature itself" comment on the relevant line.
- **Error handling**: a global `@app.exception_handler(Exception)`
  already returns a generic `{"detail": "Internal server error"}` for
  every unhandled exception, full traceback only in the server log
  (`exc_info=exc`) — already regression-tested by
  `test_an_unhandled_exception_returns_a_generic_500_never_leaking_internals`.
- **Database migrations**: `alembic heads` confirms a single linear
  head (`20261003_44`) across all 56 versions — no branching/unmerged
  heads.
- **Refund handling / payment reconciliation**: both already
  extensively built and tested (Phases 23-25, 30, 36, 38) —
  re-confirmed present and correct, not re-audited from scratch in
  this phase.
- **Environment variable documentation**: `.env.example` ships every
  Razorpay variable blank with an explanatory comment (never a fake
  key), and the placeholder `JWT_SECRET_KEY` value it ships is itself
  on the `_INSECURE_JWT_SECRETS` blocklist so it can never
  accidentally work in production.

## Files removed
- `rzp-test-key.csv` (staged for removal via `git rm --cached`, not committed)

## Files created
- `docs/payments/phase-40-production-payment-readiness.md`

## Files modified
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/tests/test_security.py`
- `docs/payments/phase-5-payment-api-design.md`
- `docs/payments/README.md`

## Testing
- New: 6 tests in `test_security.py` — 2 for the Razorpay production
  guards (test-mode key rejected, half-configured webhook secret
  rejected, COD-only production accepted), 2 for docs-disabling logic
  (`_should_enable_docs` unit test + a real-app integration test
  confirming docs stay reachable in this non-production test
  environment), 2 for `/health` (database reachable → 200, database
  unreachable → 503).
- Full backend suite: **1246 passed, 10 skipped, 0 failed** (baseline
  1240 + 6 new).

## Live verification
Not applicable in the usual sense — this phase's changes are startup
configuration guards, docs-visibility, and a new endpoint; none
require a live Razorpay/Postgres round trip beyond what the new
`/health` test already exercises against the real configured
`DATABASE_URL`.

## Known limitations
1. **The leaked Razorpay test-mode key/secret has not been rotated** —
   this requires Razorpay dashboard access this environment doesn't
   have. Must be done by the user before this key could be considered
   safe to leave un-rotated.
2. Whether to rewrite git history to remove the secret from past
   commits entirely is left to the user's judgment (a real tradeoff:
   force-push affects every clone).
3. No APM/error-tracking SDK (Sentry etc.) was added — flagged as a
   recommendation, not implemented, since it's new infrastructure
   this phase's own instruction says not to add pre-emptively.
4. `customer-mobile/.env.development` / `rider-mobile/.env.development`
   remain tracked by git (confirmed empty of secrets, but tracking any
   `.env.development` at all is itself an anti-pattern worth
   revisiting in a future phase).
