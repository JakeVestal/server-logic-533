-- Robin's schema. Database name: robin. Container: CT 201.
-- This file is the record. Luffy applies it once via
-- host_files/apply_robin_schema.sh. Deploy does not run it.
--
-- Sanji (CT 200) is the only writer. Students use student_ro.
-- Passwords are not in this file.
--
-- Legacy IB-centric tables (assets, price_bars) remain for the course job.
-- New vendor-neutral tables support tracked equities and sticky option admission.
-- Adjusted prices only for now. Never invent missing data.

-- Legacy tables (course afternoon job). No DROP — data is live.
CREATE TABLE IF NOT EXISTS assets (
  conid      BIGINT PRIMARY KEY,
  symbol     TEXT NOT NULL,
  name       TEXT,
  sec_type   TEXT NOT NULL,
  exchange   TEXT,
  currency   TEXT NOT NULL DEFAULT 'USD',
  strike     NUMERIC,
  expiry     DATE,
  contract_right TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS assets_symbol_idx ON assets (symbol);

COMMENT ON TABLE assets IS 'One IB contract. Primary key is the IB conid.';
COMMENT ON COLUMN assets.contract_right IS 'Option right: C or P. Null for non-options.';

CREATE TABLE IF NOT EXISTS price_bars (
  conid    BIGINT NOT NULL REFERENCES assets (conid) ON DELETE CASCADE,
  bar_size TEXT   NOT NULL,
  bar_date DATE   NOT NULL,
  open     NUMERIC NOT NULL,
  high     NUMERIC NOT NULL,
  low      NUMERIC NOT NULL,
  close    NUMERIC NOT NULL,
  volume   BIGINT,
  PRIMARY KEY (conid, bar_size, bar_date)
);

COMMENT ON TABLE price_bars IS 'OHLCV bars. One row per contract, bar size, and session date.';
COMMENT ON COLUMN price_bars.bar_size IS 'IB barSizeSetting, e.g. 1 day.';
COMMENT ON COLUMN price_bars.bar_date IS 'Session date. Not a timestamp.';

-- Vendor-neutral instrument identity
CREATE TABLE IF NOT EXISTS instruments (
  instrument_id         BIGSERIAL PRIMARY KEY,
  sec_type              TEXT NOT NULL,
  underlying_id         BIGINT REFERENCES instruments(instrument_id),
  symbol                TEXT NOT NULL,
  expiry                DATE,
  last_trade_date       DATE,
  strike                NUMERIC,
  contract_right        TEXT,
  multiplier            NUMERIC,
  trading_class         TEXT,
  currency              TEXT NOT NULL DEFAULT 'USD',
  exchange              TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (underlying_id, expiry, strike, contract_right, multiplier)
);

COMMENT ON TABLE instruments IS 'Vendor-neutral instrument. Options identified by underlying + expiry + strike + contract_right + multiplier.';
COMMENT ON COLUMN instruments.expiry IS 'Precise expiry date from IB contract details (YYYY-MM-DD).';
COMMENT ON COLUMN instruments.last_trade_date IS 'Actual last trading day. Prefer this for tracking end when it differs from expiry.';
COMMENT ON COLUMN instruments.contract_right IS 'Option right: C or P. Null for non-options.';
COMMENT ON COLUMN instruments.multiplier IS 'From IB. Application must error if != 100 for options.';

CREATE TABLE IF NOT EXISTS vendor_ids (
  instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  vendor          TEXT NOT NULL,
  vendor_id       TEXT NOT NULL,
  PRIMARY KEY (vendor, vendor_id),
  UNIQUE (instrument_id, vendor)
);

COMMENT ON TABLE vendor_ids IS 'Map from vendor identifier (IB conid or LSEG RIC) to instrument.';

-- Descriptive metadata
CREATE TABLE IF NOT EXISTS instrument_details (
  instrument_id       BIGINT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  short_name          TEXT,
  full_name           TEXT,
  industry            TEXT,
  sector              TEXT,
  primary_exchange    TEXT,
  country             TEXT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE instrument_details IS 'Descriptive metadata for filtering and analysis. Null stays null.';

-- Adjusted daily bars. Volume for liquidity. Open interest for options.
CREATE TABLE IF NOT EXISTS daily_bars (
  instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  bar_date        DATE NOT NULL,
  open            NUMERIC NOT NULL,
  high            NUMERIC NOT NULL,
  low             NUMERIC NOT NULL,
  close           NUMERIC NOT NULL,
  volume          BIGINT,
  open_interest   BIGINT,
  vendor          TEXT NOT NULL,
  PRIMARY KEY (instrument_id, bar_date)
);

COMMENT ON TABLE daily_bars IS 'Adjusted OHLC. Volume for liquidity. open_interest null for equities.';
COMMENT ON COLUMN daily_bars.open_interest IS 'From IB for options. Null for equities.';

CREATE TABLE IF NOT EXISTS equity_volatilities (
  instrument_id           BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  as_of_date              DATE NOT NULL,
  implied_vol_30d         NUMERIC,
  historical_vol_30d      NUMERIC,
  source                  TEXT,
  PRIMARY KEY (instrument_id, as_of_date)
);

COMMENT ON TABLE equity_volatilities IS 'LSEG 30-day vols. Null stays null. Never invent.';
COMMENT ON COLUMN equity_volatilities.implied_vol_30d IS 'TR.ImpliedVolatility30D, annualized decimal.';
COMMENT ON COLUMN equity_volatilities.historical_vol_30d IS 'TR.Volatility30D, annualized decimal.';

CREATE TABLE IF NOT EXISTS option_greeks (
  instrument_id   BIGINT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
  as_of_date      DATE NOT NULL,
  iv              NUMERIC,
  delta           NUMERIC,
  gamma           NUMERIC,
  theta           NUMERIC,
  vega            NUMERIC,
  source          TEXT,
  PRIMARY KEY (instrument_id, as_of_date)
);

COMMENT ON TABLE option_greeks IS 'Reserved for real Greeks/option IV. Empty until a source exists.';

CREATE TABLE IF NOT EXISTS tracked_underlyings (
  instrument_id   BIGINT PRIMARY KEY REFERENCES instruments(instrument_id),
  onboarded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  equity_seeded   BOOLEAN NOT NULL DEFAULT false
);

COMMENT ON TABLE tracked_underlyings IS 'Equities that have been onboarded for sticky option tracking.';

CREATE TABLE IF NOT EXISTS admission_events (
  id                BIGSERIAL PRIMARY KEY,
  underlying_id     BIGINT NOT NULL REFERENCES instruments(instrument_id),
  as_of_date        DATE NOT NULL,
  spot              NUMERIC NOT NULL,
  iv_used           NUMERIC,
  iv_source         TEXT,
  band_low          NUMERIC,
  band_high         NUMERIC,
  contracts_added   INT NOT NULL DEFAULT 0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE admission_events IS 'Audit of each 1SD band decision. Actual values only.';

-- Coverage view for QA
CREATE OR REPLACE VIEW instrument_coverage AS
SELECT
  i.instrument_id,
  i.sec_type,
  i.symbol,
  i.underlying_id,
  i.expiry,
  i.last_trade_date,
  MIN(b.bar_date) AS first_bar_date,
  MAX(b.bar_date) AS last_bar_date,
  COUNT(b.bar_date) AS bar_count
FROM instruments i
LEFT JOIN daily_bars b ON b.instrument_id = i.instrument_id
GROUP BY i.instrument_id, i.sec_type, i.symbol, i.underlying_id, i.expiry, i.last_trade_date;

COMMENT ON VIEW instrument_coverage IS 'First/last bar and count per instrument for coverage QA.';

-- Roles (idempotent)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'student_ro') THEN
    CREATE ROLE student_ro LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'robin_writer') THEN
    CREATE ROLE robin_writer LOGIN;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE robin TO student_ro, robin_writer;
GRANT USAGE ON SCHEMA public TO student_ro, robin_writer;

GRANT SELECT ON assets, price_bars TO student_ro;
GRANT SELECT, INSERT, UPDATE ON assets, price_bars TO robin_writer;

GRANT SELECT ON instruments, vendor_ids, daily_bars, equity_volatilities, option_greeks, tracked_underlyings, admission_events, instrument_details TO student_ro;
GRANT SELECT, INSERT, UPDATE ON instruments, vendor_ids, daily_bars, equity_volatilities, option_greeks, tracked_underlyings, admission_events, instrument_details TO robin_writer;

GRANT SELECT ON instrument_coverage TO student_ro, robin_writer;
