-- 011: NASA POWER monthly climate on a 0.5 x 0.625 degree grid, Bangladesh, 2001-2025 (104 points).
-- Filled by: python scripts\import_nasa_climate.py <csv>. HISTORY only - never shown as a forecast.
-- Note: t2m_max / t2m_min are the hottest / coldest values in that month (not the average daily high / low).
BEGIN;
CREATE TABLE IF NOT EXISTS climate_grid_monthly (
  lat         numeric(6,3) NOT NULL,
  lon         numeric(7,3) NOT NULL,
  year        smallint NOT NULL CHECK (year BETWEEN 1981 AND 2100),
  month       smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
  t2m         numeric(5,2),
  t2m_max     numeric(5,2),
  t2m_min     numeric(5,2),
  precip_mm_day numeric(6,2) CHECK (precip_mm_day IS NULL OR precip_mm_day >= 0),
  rh2m        numeric(5,2) CHECK (rh2m IS NULL OR rh2m BETWEEN 0 AND 100),
  solar       numeric(6,2),
  source      text NOT NULL DEFAULT 'NASA POWER monthly (Bangladesh_Climate_Master_Fixed_2001_2025.csv)',
  PRIMARY KEY (lat, lon, year, month)
);
CREATE INDEX IF NOT EXISTS ix_climate_grid_point_month ON climate_grid_monthly (lat, lon, month);
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 11 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 11)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''011_climate_grid'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''011_climate_grid'')';
  END IF;
END $$;
COMMIT;
/* ROLLBACK: DROP TABLE climate_grid_monthly; DELETE FROM schema_migrations WHERE version::text IN ('11','011_climate_grid'); */
