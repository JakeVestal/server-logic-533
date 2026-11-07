-- Options shopping list and option bars.
-- All new columns nullable. Missing stays missing.

CREATE TABLE IF NOT EXISTS options_shopping_list (
  underlying     TEXT NOT NULL,
  expiry         DATE NOT NULL,
  strike         NUMERIC NOT NULL,
  p_untracked    BOOLEAN NOT NULL DEFAULT TRUE,
  c_untracked    BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (underlying, expiry, strike)
);

COMMENT ON TABLE options_shopping_list IS 'Contracts we want but have not fully seeded. Both flags FALSE means done.';

CREATE TABLE IF NOT EXISTS option_bars (
  instrument_id            BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  bar_date                 DATE NOT NULL,
  open                     NUMERIC,
  high                     NUMERIC,
  low                      NUMERIC,
  close                    NUMERIC,
  volume                   BIGINT,
  open_interest            BIGINT,
  implied_vol              NUMERIC,
  delta                    NUMERIC,
  gamma                    NUMERIC,
  theta                    NUMERIC,
  vega                     NUMERIC,
  rho                      NUMERIC,
  bid                      NUMERIC,
  ask                      NUMERIC,
  mid                      NUMERIC,
  vendor                   TEXT NOT NULL DEFAULT 'lseg',
  PRIMARY KEY (instrument_id, bar_date)
);

COMMENT ON TABLE option_bars IS 'Daily option bars. Null stays null. Never invent.';

CREATE INDEX IF NOT EXISTS option_bars_date_idx ON option_bars (bar_date);

-- Progress: how many untracked puts/calls remain
CREATE OR REPLACE VIEW options_shopping_progress AS
SELECT
  underlying,
  COUNT(*) FILTER (WHERE p_untracked) AS puts_untracked,
  COUNT(*) FILTER (WHERE c_untracked) AS calls_untracked,
  COUNT(*) AS total_rows
FROM options_shopping_list
GROUP BY underlying
ORDER BY underlying;

COMMENT ON VIEW options_shopping_progress IS 'Untracked puts and calls still on the shopping list.';

-- Grants
GRANT SELECT ON options_shopping_list, option_bars, options_shopping_progress TO student_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON options_shopping_list, option_bars TO robin_writer;
