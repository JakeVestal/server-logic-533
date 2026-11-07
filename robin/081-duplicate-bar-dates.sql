-- View of daily bars that share the same instrument and date.
-- Empty is healthy. Rows here should be investigated and cleaned.
CREATE OR REPLACE VIEW duplicate_bar_dates AS
SELECT
  instrument_id,
  bar_date,
  COUNT(*) AS row_count
FROM daily_bars
GROUP BY instrument_id, bar_date
HAVING COUNT(*) > 1;

COMMENT ON VIEW duplicate_bar_dates IS 'Instruments with more than one bar on the same date. Empty is healthy.';
