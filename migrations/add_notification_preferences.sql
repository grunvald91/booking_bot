-- Configurable owner/master/admin reminders for each business.
ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS staff_reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS staff_reminder_first_hours INTEGER NOT NULL DEFAULT 24,
  ADD COLUMN IF NOT EXISTS staff_reminder_second_hours INTEGER NULL DEFAULT 2,
  ADD COLUMN IF NOT EXISTS staff_notify_owners BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS staff_notify_masters BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS staff_notify_admins BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE businesses
SET staff_reminder_first_hours = 24
WHERE staff_reminder_first_hours IS NULL OR staff_reminder_first_hours < 1 OR staff_reminder_first_hours > 168;

UPDATE businesses
SET staff_reminder_second_hours = 2
WHERE staff_reminder_second_hours IS NOT NULL
  AND (staff_reminder_second_hours < 1 OR staff_reminder_second_hours > 168);
