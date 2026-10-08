-- Run AFTER the new API, frontend and expiry worker are live and healthy.
-- Existing quoted rentals with an explicit positive deposit get a full window.
-- Repeating this does not reset already-running payment deadlines.
UPDATE bookings
SET status = 'pending_prepayment',
    prepayment_requested_at = timezone('UTC', CURRENT_TIMESTAMP)
WHERE duration_minutes IS NOT NULL
  AND status = 'pending'
  AND prepayment_amount > 0
  AND price_requires_confirmation = FALSE;
