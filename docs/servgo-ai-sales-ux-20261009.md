# ServGo AI sales UX & bulk review — 2026-10-09

This branch builds on `fix/servgo-auth-recovery-20261009`; it is **not** a production release.

## Changes
- `web/api/sales/engine.py` supplies a compact, tenant-scoped current catalog on the first LLM request. Avoid a redundant `get_services` → another LLM round when IDs are visible.
- `service_match.py` ranks real services using Russian forms, a few domain synonyms and typo similarity; the prompt asks to **confirm** approximate equivalents (e.g. «помывка колёс» → «Помывка шин»). No LLM-made service IDs or automatic bookings.
- `ClaudeHubClient` reuses its HTTP connection for one chat turn and logs upstream round latency **without customer text**.
- `ChatPage` displays a small circular re-send icon for failed messages.
- `PrepaymentsPage` adds per-row selection and paged "Выбрать все заявки" (up to 500 for selected business), with explicit confirmation, progress, and rechecks of related visit rows that were already updated.

**Important:** bulk review is an orchestrated set of existing single-record review requests, **not** one database-atomic action. Existing server endpoints enforce owner access, booking version and whole-visit transitions. A partial result can occur if the network fails. UI reports successes, related items already updated, and failures separately. A real bank transfer must be checked before confirming the receipt; a client's claim or screenshot alone does not prove it. No customer prepayments were changed during development.

## Validate offline before release
```bash
# In Codespaces, on THIS feature branch, without GitHub Actions:
python -m pytest -q tests/test_sales_catalog_matching.py tests/test_sales_agent.py tests/test_email_auth_and_payments.py
python -m compileall -q web/api/sales web/api/routes
cd web/frontend
npm ci --legacy-peer-deps --no-audit --no-fund
npm run build
```
Run with test-only PostgreSQL/SQLite and fake ClaudeHub/Telegram, never production data.

## Required predeployment checks
1. Reconcile production sources, migrations and current API routes with branch; do not blindly replace server files or the frontend.
2. Verify stale-token recovery / Telegram authentication from issue #36 works in the same release.
3. Back up server code, static dist and DB before any schema changes; deploy narrowly with health check and rollback.
4. Run an authenticated staging test in a tyre shop: «помывка колёс, R16» finds the real «Помывка шин» as a **suggestion** and asks whether this is what the client means.
5. Verify a different tenant never appears in catalog search or model context.
6. Compare first-token/total response latency in real server logs before and after on identical prompts; do not claim speed improvement without measurements.
7. Test the queue for a single visit with multiple services, stale version from another owner, business switching mid-batch, 150 synthetic pending claims and interrupted network. Never mass-confirm production payments as a test.
8. Verify notification and review history for each changed visit.

## Operational notes
- The LLM can still make additional calls for prices, specialists and availability; caching the catalog will not eliminate genuine checks or upstream ClaudeHub latency.
- 150 items still cause one server review request per selected booking, so bulk processing may be lengthy; a future durable server-side batch queue could optimize throughput and resumability.
- The login issue #36 is separate and remains open until tested in production.
- `AGENTS.md`: GitHub Actions are budget-constrained, prefer Codespaces/local tests and server deployment.
