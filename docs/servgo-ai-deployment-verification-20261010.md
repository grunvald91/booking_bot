# ServGo AI chat — production verification, 2026-10-10

## Confirmed result

Verified live at https://servgo.ru/chat?business_id=8 through the existing GitHub Codespace. GPT-6 Luna responds, the user's message is visible while sending, real availability is shown in an interactive card, and selecting a time opens the booking confirmation card. The test used the demo massage business. No name, phone, payment, or final booking confirmation was submitted; the pending suggestion was cancelled.

The active published admin bundle includes the **AI Growth OS** card linking to https://growth.servgo.ru, with a new tab and `noopener noreferrer`. This was checked in the deployed active bundle and its matching source. An authenticated admin browser session was not used.

## Deployment history and current release

Requested branch: `fix/ai-booking-chat-ux-20261008`.
Reviewed code/script commit: `3a9617265f96631205b00e04b03d1e3ba8914e59`.

The earlier executions of `scripts/deploy_ai_chat_codespace.sh` on October 9 rolled back:
1. A strict public HTML comparison rejected the existing nginx Telegram/shared-auth injection; the verifier was corrected to accept only the audited rewrite.
2. The actual GPT-6 Luna function-calling probe received upstream HTTP 502. Original API files and the complete frontend were restored and verified.

Rollback archives remain on the server:
- `/opt/booking_bot/.releases/ai-chat-before-20261009T045359Z.tar.gz`
- `/opt/booking_bot/.releases/ai-chat-before-20261009T045816Z.tar.gz`

On October 10, fresh inspection found a subsequent, broader production release already installed. It contains the requested chat fixes and Growth link. GitHub comparison confirms that `feat/servgo-ai-speed-catalog-bulk-payments-20261009` head `b3d72a80f491f5749056a5c71e5a90915671a1b5` descends from the requested branch's reviewed commit (24 ahead, 0 behind).

The current live source is the reconciled Codespace tree `/workspaces/servgo-speed-release`, not a byte-for-byte checkout of that newer remote head: 65 of 68 scoped Git blobs match, while `service_match.py`, `src/api/client.ts` and `PrepaymentsPage.tsx` contain subsequent reconciled edits. All seven originally scoped backend files match production, as does `service_match.py`. Rebuilding the reconciled frontend reproduces the live files exactly. The older feature payload was therefore not uploaded over this working release.

## Fresh verification

- Python 3.12: `tests/test_sales_agent.py` and `tests/test_email_auth_and_payments.py`: **74 passed, 11 skipped**, exit 0.
- `tests/test_sales_catalog_matching.py`: **3 passed**, exit 0.
- The 11 skipped tests require dedicated PostgreSQL integration configuration; no production database tests or migrations were run.
- `npm ci --legacy-peer-deps --no-audit --no-fund` and `npm run build`: exit 0, including TypeScript and Vite.
- All **16** newly built frontend files match the server's published dist byte-for-byte.
- Public active JS, CSS and runtime assets match the new build byte-for-byte.
- Active entry: `assets/index-DNa_EQN4.js`; CSS: `assets/index-Dod4eIiH.css`; runtime: `assets/jsx-runtime-CBxSU1Q0.js`.
- Live `index.html` SHA-256: `dc0cd263940784a9db715afe4d8e94db2654f7d04a06cfbff301888eb06cd7e6`.
- `booking-web-api`: active. Local `/health`: `{"status":"ok"}`. Chat/select-slot and other AI endpoints present in OpenAPI.
- Running service model override/default verified as `gpt-6-luna` without exposing credentials.
- Provider model availability: HTTP 200, Luna status `ok`.
- Real harmless function-call request: HTTP **200**, response model `gpt-6-luna`, correct function call, **4.68 seconds**. It used `reasoning_effort=none`, `max_completion_tokens=850`, `tool_choice=auto`.
- Browser walkthrough: prompt → availability → selected time → confirmation card → cancel. No customer booking created.
- `bash -n scripts/deploy_ai_chat_codespace.sh`: passed.
- GitHub Actions were not started; the requested branch's Actions runs count was **0** at verification.

Codespace logs:
`/workspaces/servgo-verification-20261010-tests.log`,
`/workspaces/servgo-verification-20261010-catalog.log`,
`/workspaces/servgo-verification-20261010-build.log`.

## Current verified backup

Created on the production server at 2026-10-10 10:10:10 UTC:

`/opt/booking_bot/.releases/ai-chat-verified-20261010T101010Z.tar.gz`

It contains the seven scoped backend files and complete current frontend dist. No database/schema change was made during this verification.

- gzip integrity: passed
- permissions: `0600`
- SHA-256: `85dc8fccdd9f6eb6115ddf60271dcb489ccb1af5f0f2813cad3a166105456c4c`

The current production release remains running and its requested chat behavior is confirmed.
