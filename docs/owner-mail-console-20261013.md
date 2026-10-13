# ServGo: owner mail console — deployment

Implementation branch: feat/owner-mail-console-20261013. Not deployed to production.

## Owner-only security
- ServGo booking authentication stays authoritative. Permission endpoint GET /api/owner-mail/permission tests the real DB user against the platform-owner ID (not the business admin role).
- POST /api/owner-mail/entry issues a signed one-minute link, exchanged once at mail.servgo.ru/claim.
- A Secure, HttpOnly, SameSite=Strict 8-hour cookie provides the mail-only session. All HTML and API routes check it.
- Platform-owner ID must be provided through SERVGO_MAIL_OWNER_USER_ID or SERVGO_MAIL_OWNER_TELEGRAM_ID. No ID configured means no access.

## Required Booking API runtime environment (never commit secrets)
- SERVGO_MAIL_OWNER_USER_ID or SERVGO_MAIL_OWNER_TELEGRAM_ID — exact owner ID. Verify from database.
- SERVGO_MAIL_SESSION_SECRET — separately generated random secret of 32+ characters.
- SERVGO_MAIL_DATA_DIR — existing 0700 directory writable by web API service user, e.g. /var/lib/servgo-owner-mail.
- SERVGO_MAIL_FROM — existing verified sender mailbox on servgo.ru.
- SERVGO_MAIL_IMAP_USER and SERVGO_MAIL_IMAP_PASSWORD — real IMAP credentials (only if IMAP is deployed).
- CLAUDEHUB_API_KEY (or XAI_API_KEY if already present in Booking API service).
- SERVGO_MAIL_AI_MODEL — actual model enabled by ClaudeHub Chat Completions; default grok-4.7.

Keys and credentials must remain in protected service environment, never inside HTML or GitHub.

## Nginx conceptual example
Replace TLS certificate paths ONLY AFTER checking the installed certificate and actual nginx config.
Do not change SMTP ports 25, 465 or 587. Do not replace the existing mail host record.

    server {
        listen 443 ssl;
        server_name mail.servgo.ru;
        ssl_certificate /verified/existing/fullchain.pem;
        ssl_certificate_key /verified/existing/privkey.pem;
        add_header Cache-Control "no-store" always;
        add_header Referrer-Policy "no-referrer" always;
        location = / {
            proxy_pass http://127.0.0.1:8000/owner-mail/app;
            proxy_set_header Host $host;
        }
        location = /claim {
            access_log off;
            proxy_pass http://127.0.0.1:8000/owner-mail/claim;
            proxy_set_header Host $host;
        }
        location /api/ {
            proxy_pass http://127.0.0.1:8000/owner-mail/api/;
            proxy_set_header Host $host;
        }
        location / { return 404; }
    }

Main servgo.ru Nginx must already proxy /api/owner-mail requests to Booking API. Test nginx -t before reloading.

## Features in this branch
- Import companies one at a time or in semicolon-delimited list: company; email; HTTPS website; notes; consent evidence.
- Safe public HTTPS reading with IP pinning, no redirects, bounded response. No general-purpose search service yet.
- Individual personalized draft per company through ClaudeHub. Second critic pass identifies critical mistakes, with bounded revision.
- One-at-a-time owner approval and manual sending ONLY with recorded prior advertising consent; 20 per 24 hours.
- Reserves the send before SMTP; ambiguous sending errors are not retried automatically. SMTP accepted does not equal delivered.
- IMAP 993 inbox headers and safe plain-text message display IF server has working IMAP and mailbox credentials.
- Authentication is server-enforced, not based on CSS or localStorage userRole.

## Before any production deployment
1. Confirm live Booking environment and user identity.
2. Inspect TLS certificate for mail.servgo.ru, reverse proxy, and local Postfix.
3. Confirm Dovecot/IMAP availability; SMTP readiness alone does not prove it.
4. Test owner, unauthenticated, business admin, staff, expired link, reused link, logout.
5. Verify local SMTP to owner's own address and DKIM/SPF results; do not send marketing messages in tests.
6. Run Python compile checks, backend tests, React build and nginx validation using Codespaces/local SSH WITHOUT GitHub Actions.
7. Check advertising consent under article 18 of 38-FZ and suppression behavior.
8. Deploy only after review; do not overwrite existing mail server or nginx blocks blindly.

No deployment, code execution on the live host, or successful mail delivery is claimed by this branch.
