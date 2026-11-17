-- 009: Admin A3 — announcements workflow, articles/news, offline sync log, admin cancel reasons for forecasts/requests.
-- Safe to re-run. Existing announcements stay published (farmers keep seeing them). Rollback block at the end.
BEGIN;

-- 1) announcements: draft / published / archived; in-app delivery recorded (no duplicates) -------------------------
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'published';
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS published_at timestamptz;
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS notified_at timestamptz;
ALTER TABLE announcements ADD COLUMN IF NOT EXISTS notified_count integer;
UPDATE announcements SET published_at = created_at WHERE published_at IS NULL AND status = 'published';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'announcements_status_check') THEN
    ALTER TABLE announcements ADD CONSTRAINT announcements_status_check CHECK (status IN ('draft', 'published', 'archived'));
  END IF;
END $$;

-- 2) public articles / news / videos (real content only; source shown) ------------------------------------------------
CREATE TABLE IF NOT EXISTS content_posts (
  id           bigserial PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('article', 'news', 'video')),
  title        text NOT NULL CHECK (length(title) BETWEEN 3 AND 160),
  summary      text CHECK (summary IS NULL OR length(summary) <= 400),
  body         text NOT NULL CHECK (length(body) BETWEEN 10 AND 20000),
  media_url    text CHECK (media_url IS NULL OR media_url ~ '^https://'),
  source_name  text CHECK (source_name IS NULL OR length(source_name) <= 160),
  source_url   text CHECK (source_url IS NULL OR source_url ~ '^https?://'),
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  published_at timestamptz,
  created_by   bigint REFERENCES users(id) ON DELETE SET NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'published' OR published_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_content_public ON content_posts (status, published_at DESC);

-- 3) offline sync log (what the server saw; never the farmer's private draft content) ----------------------------------
CREATE TABLE IF NOT EXISTS offline_sync_events (
  id          bigserial PRIMARY KEY,
  farmer_id   bigint REFERENCES users(id) ON DELETE CASCADE,
  record_type text NOT NULL CHECK (record_type IN ('forecast', 'listing')),
  client_id   uuid,
  result      text NOT NULL CHECK (result IN ('created', 'updated', 'duplicate', 'conflict', 'rejected', 'error')),
  http_status integer NOT NULL,
  detail      text CHECK (detail IS NULL OR length(detail) <= 120),
  server_id   bigint,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sync_events ON offline_sync_events (result, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_sync_events_farmer ON offline_sync_events (farmer_id, created_at DESC);

-- 4) record the migration --------------------------------------------------------------------------------------------
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 9 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 9)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''009_admin_a3'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''009_admin_a3'')';
  END IF;
END $$;

COMMIT;

/* ROLLBACK (by hand only):
BEGIN;
DROP TABLE IF EXISTS offline_sync_events, content_posts;
DELETE FROM announcements WHERE status = 'draft';          -- drafts would otherwise show as tips
ALTER TABLE announcements DROP CONSTRAINT IF EXISTS announcements_status_check;
DELETE FROM schema_migrations WHERE version::text IN ('9', '009_admin_a3');
COMMIT;
*/
