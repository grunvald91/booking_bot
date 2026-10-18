# Production vs GitHub — audit 2026-10-18

Read-only audit of `155.212.162.47` (workflow `server-sync-audit`, run 39147676931). Every source file on the
server was hashed and compared with `main`, every branch tip and the full history of `booking_bot`,
`Ai_growth_os` and `SMENA`.

## `/opt/booking_bot` (booking bot, web API, webapp, blog, owner mail)

- Application code (`bot/`, `database/`, `web/api/`, `webapp/`, `migrations/`) matches `main`, except:
  - `web/api/routes/admin.py`: **main is newer** — the server lacks `list(result.scalars().all())` (line 731).
    Deploy gap, not a GitHub gap.
  - `webapp/static/blog/*.svg` (9 article illustrations) are served in production but existed only on
    `feature/servgo-public-blog`. **Added to this branch.**
- Frontend sources on the server (`web/frontend/src`) are older than `main` (`AdminShell.tsx`) or from
  `feat/owner-mail-console-20261013` (`OwnerMailEntry.tsx`); `main` already has newer versions. The served
  build is `web/frontend/dist`, not compared (build output).
- Server-only files added here at their server paths: `docs/ai/…`, `docs/plans/2026-03-09-ai-admin.md`,
  `docs/server-acceptance-20261008.md`, `docs/superpowers/…`, `tests/servgo_*_check.py`.
- Not added on purpose: root `server.py` (stale copy of `webapp/server.py`), `apply_security_patches.py` and
  `patch_idor.py` (one-off March patches whose result is already in `main`), `backup_*`, `deploy_backups/`,
  `releases/`, `_*_backup_*` and `web/frontend/dist.*` (old copies and build backups).
- Present in `main` but not on the server: 17 operator scripts under `scripts/` (run from CI/Codespaces).

## Ops added here

- `deploy/ops/20261015/`: scripts used for the 2026-10-15 mail and blog releases (they read secrets from the
  service environment; nothing secret is in the code).
- `nginx/`: the platform's enabled sites (`webapp` = servgo.ru, `mail-servgo`, `servgo-promo`, `tech-servgo`).
- `systemd/`: `booking-bot`, `booking-web-api`, relay and mail-worker units with drop-ins.
  **Secret values are replaced with `<redacted>`**; real values live only on the server.
- `DEPLOYED_RELEASE.json`, `release_scope.json`: the server's own record of the last scoped release.

Growth (`/app` in the api container, `/opt/ai_growth_os`) and the SMENA QR screen are recorded in their own
repositories.
