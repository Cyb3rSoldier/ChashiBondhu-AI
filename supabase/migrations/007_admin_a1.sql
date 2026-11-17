-- 007: Admin A1 — staff permissions, permanent audit log, user suspension, listing moderation, review moderation.
-- Safe to re-run. Existing admins become Super Admins (so nobody is locked out). Rollback block at the end.
BEGIN;

-- 1) users.status must allow 'suspended' (keeps every value the old rule allowed) ------------------------
DO $$
DECLARE r record; vals text[] := ARRAY['active', 'suspended']; v text;
BEGIN
  FOR r IN SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint
           WHERE conrelid = 'public.users'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) ~ '\mstatus\M' LOOP
    -- every word in the old rule that is not SQL is an allowed value (works for IN (...), ARRAY[...] and '{...}')
    FOR v IN SELECT (regexp_matches(lower(r.d), '([a-z_]+)', 'g'))[1] LOOP
      IF v NOT IN ('check', 'status', 'any', 'array', 'text', 'in', 'or', 'and', 'is', 'null', 'not', 'character',
                   'varying') AND NOT v = ANY(vals) THEN
        vals := vals || v;
      END IF;
    END LOOP;
    EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', r.conname);
  END LOOP;
  FOR v IN SELECT DISTINCT status FROM users LOOP
    IF NOT v = ANY(vals) THEN vals := vals || v; END IF;
  END LOOP;
  EXECUTE format('ALTER TABLE users ADD CONSTRAINT users_status_check CHECK (status = ANY (%L::text[]))', vals);
END $$;
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_reason text;

-- 2) admin staff + permissions ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_staff (
  user_id     bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  is_super    boolean NOT NULL DEFAULT false,
  permissions text[]  NOT NULL DEFAULT '{}',
  created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (permissions <@ ARRAY['dashboard', 'farmers', 'consumers', 'products', 'reviews', 'orders', 'complaints',
                              'finance', 'notifications', 'content', 'analytics', 'audit', 'staff']::text[])
);
INSERT INTO admin_staff (user_id, is_super)
SELECT id, true FROM users WHERE role = 'admin' ON CONFLICT (user_id) DO NOTHING;

-- 3) audit log: insert-only (UPDATE / DELETE / TRUNCATE are refused by the database) ---------------------
CREATE TABLE IF NOT EXISTS admin_audit_log (
  id          bigserial PRIMARY KEY,
  actor_id    bigint,                         -- plain copy (no foreign key): the log survives user removal
  actor_name  text,
  action      text NOT NULL,
  target_type text,
  target_id   bigint,
  result      text NOT NULL DEFAULT 'ok' CHECK (result IN ('ok', 'denied', 'failed')),
  reason      text CHECK (reason IS NULL OR length(reason) <= 500),
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON admin_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_target ON admin_audit_log (target_type, target_id);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON admin_audit_log (actor_id, created_at DESC);

CREATE OR REPLACE FUNCTION admin_audit_log_readonly() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'admin_audit_log is append-only' USING ERRCODE = '42501';
END $$;
DROP TRIGGER IF EXISTS trg_audit_no_update ON admin_audit_log;
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON admin_audit_log
  FOR EACH ROW EXECUTE FUNCTION admin_audit_log_readonly();
DROP TRIGGER IF EXISTS trg_audit_no_truncate ON admin_audit_log;
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON admin_audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_log_readonly();

-- 4) listing moderation: an admin-removed listing stays hidden until an admin restores it -------------------
ALTER TABLE listings ADD COLUMN IF NOT EXISTS moderated_at timestamptz;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS moderated_by bigint REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS moderation_reason text;

CREATE OR REPLACE FUNCTION listings_keep_moderated_hidden() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- the farmer (or an offline sync) cannot bring back a listing an admin removed
  IF OLD.moderated_at IS NOT NULL AND NEW.moderated_at IS NOT NULL AND NEW.status = 'active' THEN
    NEW.status := OLD.status;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_listings_keep_moderated_hidden ON listings;
CREATE TRIGGER trg_listings_keep_moderated_hidden BEFORE UPDATE ON listings
  FOR EACH ROW EXECUTE FUNCTION listings_keep_moderated_hidden();

-- 5) review moderation reason (status column came with 006) ---------------------------------------------
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS moderation_reason text;

-- 6) record the migration --------------------------------------------------------------------------------
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 7 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 7)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''007_admin_a1'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''007_admin_a1'')';
  END IF;
END $$;

COMMIT;

/* ROLLBACK (by hand only; the audit log is kept on purpose):
BEGIN;
DROP TRIGGER IF EXISTS trg_listings_keep_moderated_hidden ON listings; DROP FUNCTION IF EXISTS listings_keep_moderated_hidden();
UPDATE listings SET moderated_at = NULL WHERE moderated_at IS NOT NULL;
DROP TABLE IF EXISTS admin_staff;
UPDATE users SET status = 'active' WHERE status = 'suspended';   -- only if you really want everyone back
DELETE FROM schema_migrations WHERE version::text IN ('7', '007_admin_a1');
COMMIT;
*/
