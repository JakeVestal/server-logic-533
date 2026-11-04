-- Robin's schema. Database name: robin. Container: CT 201.
-- This file is the record. Luffy applies it once via
-- host_files/apply_robin_schema.sh. Deploy does not run it.
--
-- Sanji (CT 200) is the only writer. Students use student_ro.
-- Passwords are not in this file.
--
-- One row per IB contract. price_bars stores each daily bar once,
-- shared by every student repo that tracks that conid.
-- bar_size is part of the key because subscriptions.csv will carry
-- it later. Until then Sanji writes '1 day'.

DROP TABLE IF EXISTS price_bars;
DROP TABLE IF EXISTS assets;

CREATE TABLE assets (
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

CREATE INDEX assets_symbol_idx ON assets (symbol);

COMMENT ON TABLE assets IS 'One IB contract. Primary key is the IB conid.';
COMMENT ON COLUMN assets.contract_right IS 'Option right: C or P. Null for non-options.';

CREATE TABLE price_bars (
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
