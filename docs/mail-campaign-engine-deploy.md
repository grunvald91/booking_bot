# ServGo Mail — Campaign Engine: release checklist

Status: implemented in GitHub branch `feat/owner-mail-console-20261013`, NOT deployed to production.

## What is implemented
- `mail_campaign_store.py`: SQLite WAL-backed campaigns, recipients, events, global exclusions and analytics aggregates.
- `mail_campaign_api.py`: owner-only create/list/details and import up to 1000 email records per request without pre-existing contacts.
- `mail_campaign_review.py`: enqueue research, edit, bulk-approve personally reviewed drafts, launch/pause/finish and exclusions.
- `mail_campaign_research.py`: bounded ClaudeHub research, one personalized email per target, independent critic and focused correction.
- `mail_campaign_dispatch.py`: persistent SMTP reservation before send, configurable 24h limit, intervals, no automatic retry if delivery is uncertain.
- `mail_campaign_unsubscribe.py`: one-click unsubscribe endpoints and suppression for future sends.
- `mail_campaign_analytics.py`: campaign statistics, owner reply classification and correlation using IMAP References / In-Reply-To.
- `mail_campaign_worker.py`: single-instance background research and delivery with restart recovery.
- `mail_campaign_dashboard.html`: campaign-first interface, import, review, approval, launch, pause, reporting.
- `test_mail_campaign_engine.py`: offline mocked test scenarios, do not contact SMTP or ClaudeHub.

## Production prerequisites
1. Inspect the *live* Nginx configuration for mail.servgo.ru and certificate coverage on HTTPS 443. Existing Postfix and IMAP configuration must stay intact.
2. Confirm ServGo owner identity in the Booking database and protected auth cookies:
   - SERVGO_MAIL_OWNER_USER_ID or SERVGO_MAIL_OWNER_TELEGRAM_ID
   - SERVGO_MAIL_SESSION_SECRET (unique random secret, minimum 32 characters)
3. Confirm Booking API unit environment:
   - SERVGO_MAIL_FROM (valid existing sender address, DKIM-signed by local Postfix)
   - CLAUDEHUB_API_KEY (or XAI_API_KEY) and SERVGO_MAIL_AI_MODEL
   - SERVGO_MAIL_IMAP_USER, SERVGO_MAIL_IMAP_PASSWORD, if receiving mail
   - SERVGO_MAIL_DATA_DIR (0700, writable by Booking API and campaign worker)
   - SERVGO_MAIL_DAILY_LIMIT (default 50 per 24h)
4. Nginx mail.servgo.ru should reverse proxy:
   - / -> http://127.0.0.1:8000/owner-mail/app
   - /api/ -> http://127.0.0.1:8000/owner-mail/api/
   - /claim -> http://127.0.0.1:8000/owner-mail/claim
   - /unsubscribe -> http://127.0.0.1:8000/owner-mail/unsubscribe (public, no owner session).
5. Ensure /api/owner-mail/permission and /api/owner-mail/entry at the primary ServGo website route to the Booking API. No owner-only HTML may be served by a public static Nginx directory.

## Dedicated worker (example systemd unit)
The campaign worker must run separately from the API. Do not run it as part of every Uvicorn process.

    [Unit]
    Description=ServGo Mail campaign worker
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=booking
    Group=booking
    WorkingDirectory=/opt/booking_bot
    EnvironmentFile=/etc/servgo/mail-worker.env
    ExecStart=/opt/booking_bot/venv/bin/python -m web.api.routes.mail_campaign_worker
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target

Adjust the service user, Python location and environment file to the *actual* deployment.
The worker uses a nonblocking OS file lock and recovers interrupted jobs. Stuck sending jobs transition to UNKNOWN, not back into the dispatch queue. Only operator reconciliation can decide what to do next.

## Recommended verification (do not run GitHub Actions)
- Python 3.12 compile for all `mail_campaign*.py` modules.
- `pytest -q tests/test_mail_campaign_engine.py` with only mocked SMTP and ClaudeHub.
- Full Booking API smoke: owner can enter; anonymous, business owner, staff and expired session cannot; direct URL protected.
- Test anti-duplicate after timeout. Confirm that zero outbound marketing emails are sent in automated tests.
- Run Nginx configuration test before any reload.
- Run local SMTP test to the platform owner's own mailbox only, verify SPF/DKIM/DMARC.
- Verify an IMAP reply to a test message correctly updates analytics. Check reply classification is manual, not made up by AI.
- Run sample opt-out with an owner-controlled test address and check suppression.
- Verify no delivery claim is made from SMTP acceptance alone.

## Known bounds and next steps
- An explicit owner decision is required per set of *drafts* before launching. Queued drafts are never implicitly approved.
- API can import 1000 recipients per request and 10,000 per campaign. No pre-existing address book is required.
- Current browser UI accepts pasted address lists; native XLSX upload/CSV parsing with robust quoting still needs a dedicated implementation.
- Worker handles one message at a time and respects the configured rate limit. Compliance and permitted sending differ by market; no Russian jurisdiction is assumed by default.
- No engagement pixel, click tracking, external email-delivery webhook, or predictive deliverability score. Statistics represent observed SMTP status and replies only.
- No production deployment was performed by creating these files. Secrets must remain outside git.
