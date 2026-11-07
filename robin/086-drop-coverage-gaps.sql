-- coverage_gaps is no longer useful.
-- The loader creates a minimal instrument when a bar arrives without one,
-- so the view would always be empty.
DROP VIEW IF EXISTS coverage_gaps;
