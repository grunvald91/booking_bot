-- MNEBYVPN login reuses the existing ServGo Yandex OAuth application.
-- No app secret is copied and no access to ServGo accounts is granted.
BEGIN;
CREATE TABLE IF NOT EXISTS yandex_external_tickets (
  id varchar(64) PRIMARY KEY CHECK(id ~ '^[a-f0-9]{64}$'),
  yandex_id varchar(32) NOT NULL CHECK(yandex_id ~ '^[0-9]{1,32}$'),
  pkce_challenge varchar(43) NOT NULL CHECK(pkce_challenge ~ '^[A-Za-z0-9_-]{43}$'),
  expires_at timestamp NOT NULL,
  consumed boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_yandex_external_tickets_expiry
  ON yandex_external_tickets(expires_at);
COMMIT;
