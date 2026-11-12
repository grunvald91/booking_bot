# Shared Telegram Authentication for Servgo Services

Date: 2026-05-04

## Context

There are two related but independent services under `servgo.ru`:

- `servgo.ru`: online service booking from `booking_bot`.
- `gid.servgo.ru`: Sochi Guide from `sochi-concierge`.

Sochi Guide already has a working Telegram Login Widget flow. Users click Telegram login, approve the Telegram authorization request, and the site receives a valid authenticated session.

The booking site currently does not provide the same website login experience. It mainly supports Telegram Mini App `initData` when opened inside Telegram and a separate owner fallback via `/weblogin`, direct token links, PIN, and `owner_session` cookie. That is not the desired client-facing login behavior for the public website.

## Goal

Implement one shared Telegram authentication behavior across both services:

- A user can start on either `gid.servgo.ru` or `servgo.ru`.
- Both sites show the same Telegram login behavior.
- After logging in on either site, the user is already authenticated on the other site.
- Users can still use only one service if they never open the other.
- Each service keeps its own product logic and permissions.

## Non-Goals

- Do not make Sochi Guide the "main" service or the booking site a dependent child.
- Do not require users to visit a separate auth domain before using either product.
- Do not merge the two applications or their databases.
- Do not replace booking owner, administrator, master, or business permission checks.
- Do not remove Telegram Mini App `initData`; it should remain supported for Telegram WebApp usage.

## Recommended Design

Create a shared auth module that both Python services use. The module implements the Telegram Login Widget verification, shared session token creation, shared session validation, and logout behavior.

Both sites expose a symmetric Telegram login entry point:

- Sochi Guide keeps its current working Telegram Login Widget UI, but the backend starts issuing the shared Servgo session.
- The booking site adds the same Telegram Login Widget UI for web users and accepts the same shared session.

The shared session is stored as a secure HTTP-only cookie scoped to `.servgo.ru`, so it is available to both `gid.servgo.ru` and `servgo.ru`.

## Session Model

Use a random server-side session token, not a deterministic token derived from Telegram ID.

Session properties:

- Cookie name: `servgo_session`
- Cookie domain: `.servgo.ru`
- `HttpOnly: true`
- `Secure: true` in production
- `SameSite: Lax`
- Expiration: 30 days
- Value: random token such as `secrets.token_hex(32)`

The session record stores:

- `token_hash`
- `telegram_id`
- Telegram profile fields where available: first name, last name, username, photo URL
- `created_at`
- `expires_at`
- `is_active`
- optional `source_service`, such as `guide` or `booking`

Only the token hash is stored in the database. The raw token is returned to the browser once in the `servgo_session` cookie.

## Data Storage

Use one shared auth table set that both services can reach. The existing Sochi Guide auth tables are a good starting point:

- `web_users`
- `web_sessions`

They should become service-neutral shared auth tables. Both services should read shared auth database settings from explicit environment variables, for example `AUTH_DB_HOST`, `AUTH_DB_PORT`, `AUTH_DB_NAME`, `AUTH_DB_USER`, and `AUTH_DB_PASSWORD`. In production, both services must point these variables at the same PostgreSQL database. The product databases can remain separate.

The booking service still keeps its own `users` table. When a shared session identifies a Telegram user, booking should look up or create its local `User` row by `telegram_id` before using booking-specific features.

## Login Flow

1. User opens either site.
2. If no valid `servgo_session` cookie exists, the site shows a Telegram login button.
3. Telegram Login Widget returns signed auth data to that same site.
4. That site's backend verifies the Telegram HMAC and checks `auth_date` freshness.
5. Backend creates or updates the shared auth user.
6. Backend creates a shared random session token.
7. Backend sets `servgo_session` for `.servgo.ru`.
8. The current site becomes authenticated immediately.
9. When the user later opens the other site, that service validates the same cookie and treats the user as authenticated.

## Service-Specific Behavior

Sochi Guide:

- Continue to support anonymous chat sessions.
- On Telegram login, migrate anonymous memory/history to Telegram ID as it does today.
- Use the shared session token for `/api/auth/me`, `/api/history`, and personalized chat behavior.

Booking site:

- Continue to support public browsing and web booking where name/phone are entered manually.
- For authenticated clients, use the shared Telegram ID to create or find the local booking `User`.
- Allow client actions such as "my bookings", cancellation, reschedule, and prepayment confirmation through shared session auth.
- Keep existing owner/admin/master checks inside booking. Shared auth proves identity; booking permissions decide access.
- Keep Telegram Mini App `initData` support as an alternative identity source when opened inside Telegram.

## Backward Compatibility

Keep existing booking owner web login temporarily:

- `/weblogin`
- `/auth/token/{token}`
- phone + PIN login
- `owner_session`

These can continue to work while shared auth is rolled out. They should not be the primary user-facing Telegram login path.

After shared auth is stable, the deterministic owner token and PIN flow should be reviewed and either hardened or retired.

## Security Requirements

- Verify Telegram Login Widget data with the official HMAC flow.
- Use `hmac.compare_digest` for hash comparison.
- Reject missing or stale `auth_date`; use a 24-hour maximum age.
- Use random server-side session tokens.
- Store `sha256` hashes of session tokens in the database. Do not persist raw session tokens.
- Logout must deactivate the shared session and clear the `.servgo.ru` cookie.
- Do not trust Telegram profile data without HMAC verification.
- Shared auth only establishes identity, not business permissions.

## API Shape

Both services should expose compatible auth endpoints:

- `POST /api/auth/telegram`: accept Telegram Login Widget payload, verify it, create shared session, set cookie, return current user.
- `GET /api/auth/me`: validate `servgo_session`, return current user or 401.
- `POST /api/auth/logout`: deactivate current shared session and clear cookie.

The booking service can keep existing endpoints, but client-facing pages should use the shared endpoints for web login.

## Testing

Add tests before implementation:

- Telegram Login Widget HMAC accepts valid signed data.
- HMAC rejects tampered data.
- HMAC rejects stale `auth_date`.
- Shared session creation returns a random token and validates it.
- Logout invalidates a token.
- Booking request auth accepts `servgo_session`.
- Booking falls back to Telegram Mini App `initData` when present.
- Sochi Guide can still authenticate with the existing widget payload.

Manual verification after deploy:

1. Log in on `gid.servgo.ru` through Telegram.
2. Open `servgo.ru`; user is authenticated without another Telegram approval.
3. Log out on `servgo.ru`.
4. Refresh `gid.servgo.ru`; user is logged out there too.
5. Log in first on `servgo.ru`.
6. Open `gid.servgo.ru`; user is authenticated without another Telegram approval.
7. Open booking inside Telegram WebApp; `initData` flow still works.

## Rollout Plan

1. Extract or duplicate the shared auth module in a small, explicit way.
2. Add shared session support to Sochi Guide while preserving current behavior.
3. Add shared session support to booking backend.
4. Add Telegram Login Widget UI to booking web pages where authenticated client actions are needed.
5. Verify cross-domain cookie behavior on production domains.
6. Keep old booking owner login as fallback during rollout.
7. After stability, decide whether to retire or harden the old deterministic owner login.

## Deployment Requirement

Before production rollout, confirm that `gid.servgo.ru` and `servgo.ru` are configured with the same `AUTH_DB_*` values and that both domains are served over HTTPS. Cross-service login is not considered complete until the browser receives `servgo_session` on `.servgo.ru` and both services validate it against the same auth database.
