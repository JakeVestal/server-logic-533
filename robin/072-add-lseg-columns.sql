-- Additive columns for LSEG equity seed data.
-- All nullable. Missing stays missing.

ALTER TABLE instrument_details
  ADD COLUMN IF NOT EXISTS gics_industry_group TEXT,
  ADD COLUMN IF NOT EXISTS trbc_industry_group TEXT,
  ADD COLUMN IF NOT EXISTS organization_id TEXT,
  ADD COLUMN IF NOT EXISTS primary_ric TEXT;

ALTER TABLE daily_bars
  ADD COLUMN IF NOT EXISTS vwap NUMERIC,
  ADD COLUMN IF NOT EXISTS trade_count BIGINT,
  ADD COLUMN IF NOT EXISTS turnover NUMERIC,
  ADD COLUMN IF NOT EXISTS number_of_block_trades BIGINT;

COMMENT ON COLUMN instrument_details.gics_industry_group IS 'From LSEG TR.GICSIndustryGroup. Null stays null.';
COMMENT ON COLUMN instrument_details.trbc_industry_group IS 'From LSEG TR.TRBCIndustryGroup. Null stays null.';
COMMENT ON COLUMN instrument_details.organization_id IS 'LSEG Organization PermID. Null stays null.';
COMMENT ON COLUMN instrument_details.primary_ric IS 'LSEG Primary Issue RIC. Null stays null.';
COMMENT ON COLUMN daily_bars.turnover IS 'From LSEG TR.TURNOVER. Null stays null.';
COMMENT ON COLUMN daily_bars.number_of_block_trades IS 'From LSEG TR.NUMBEROFBLOCKTRADES. Null stays null.';
