-- ServGo: business setting "several services in one booking" (admin → Услуги).
-- Safe additive schema-only migration; apply separately to production after review.

ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS allow_multiple_services BOOLEAN NOT NULL DEFAULT FALSE;
