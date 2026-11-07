-- MNEBYVPN email OTP relay reuses ServGo's existing SMTP without exposing its credentials.
BEGIN;
CREATE TABLE IF NOT EXISTS mnebyvpn_email_dispatch_nonces (
  nonce_hash varchar(64) PRIMARY KEY,
  created_at timestamp NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);
CREATE INDEX IF NOT EXISTS ix_mnebyvpn_email_dispatch_created
  ON mnebyvpn_email_dispatch_nonces(created_at);
COMMIT;
