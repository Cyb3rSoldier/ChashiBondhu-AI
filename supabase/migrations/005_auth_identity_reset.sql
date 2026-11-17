-- 005: role-based identity + password reset.
--   Farmer : phone required, unique among farmers.     Admin: phone unique among admins.
--   Customer: email required (new accounts), unique among customers (case-insensitive); phone required, NOT unique.
--   A farmer and a customer may share a phone. No user is deleted or merged.
-- Safe to re-run. Rollback: see the comment block at the end of this file.
BEGIN;

-- 1) new columns --------------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at timestamptz;

-- normalise any emails that already exist (trim + lower case, empty -> NULL)
UPDATE users SET email = NULLIF(lower(btrim(email)), '') WHERE email IS DISTINCT FROM NULLIF(lower(btrim(email)), '');

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_email_format') THEN
    ALTER TABLE users ADD CONSTRAINT users_email_format
      CHECK (email IS NULL OR (email = lower(btrim(email)) AND length(email) <= 254
                               AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'));
  END IF;
END $$;

-- 2) stop if real duplicates exist (we never delete or merge users automatically) --------------
DO $$
DECLARE d text;
BEGIN
  SELECT string_agg(phone, ', ') INTO d FROM (SELECT phone FROM users WHERE role = 'farmer'
    GROUP BY phone HAVING count(*) > 1) x;
  IF d IS NOT NULL THEN RAISE EXCEPTION '005 stopped: duplicate FARMER phones: %. Fix them by hand, then re-run.', d; END IF;
  SELECT string_agg(phone, ', ') INTO d FROM (SELECT phone FROM users WHERE role = 'admin'
    GROUP BY phone HAVING count(*) > 1) x;
  IF d IS NOT NULL THEN RAISE EXCEPTION '005 stopped: duplicate ADMIN phones: %. Fix them by hand, then re-run.', d; END IF;
  SELECT string_agg(e, ', ') INTO d FROM (SELECT lower(email) e FROM users WHERE role = 'customer' AND email IS NOT NULL
    GROUP BY lower(email) HAVING count(*) > 1) x;
  IF d IS NOT NULL THEN RAISE EXCEPTION '005 stopped: duplicate CUSTOMER emails: %. Fix them by hand, then re-run.', d; END IF;
END $$;

-- 3) role-specific uniqueness (created BEFORE the global rule is dropped, so there is no gap) ---
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_farmer_phone   ON users (phone)        WHERE role = 'farmer';
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_admin_phone    ON users (phone)        WHERE role = 'admin';
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_customer_email ON users (lower(email)) WHERE role = 'customer';
CREATE INDEX        IF NOT EXISTS ix_users_phone          ON users (phone);

-- 4) drop the old GLOBAL unique rule on phone (whatever its name is) ---------------------------
DO $$
DECLARE r record; ph smallint;
BEGIN
  SELECT attnum INTO ph FROM pg_attribute WHERE attrelid = 'public.users'::regclass AND attname = 'phone';
  FOR r IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'public.users'::regclass AND contype = 'u' AND conkey = ARRAY[ph] LOOP
    EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', r.conname);
  END LOOP;
  FOR r IN SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
           WHERE i.indrelid = 'public.users'::regclass AND i.indisunique AND NOT i.indisprimary
             AND i.indpred IS NULL AND i.indexprs IS NULL AND i.indkey::text = ph::text LOOP
    EXECUTE format('DROP INDEX %I', r.relname);
  END LOOP;
END $$;

-- 5) NEW customers must have an email (old customers keep working until they add one) ----------
CREATE OR REPLACE FUNCTION users_require_customer_email() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role = 'customer' AND NEW.email IS NULL THEN
    RAISE EXCEPTION 'customer accounts need an email' USING ERRCODE = '23502';
  END IF;
  IF NEW.role IN ('farmer', 'admin') AND (NEW.phone IS NULL OR btrim(NEW.phone) = '') THEN
    RAISE EXCEPTION 'farmer/admin accounts need a phone' USING ERRCODE = '23502';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_users_require_customer_email ON users;
CREATE TRIGGER trg_users_require_customer_email BEFORE INSERT ON users
  FOR EACH ROW EXECUTE FUNCTION users_require_customer_email();

-- 6) password reset codes / links (only HASHES are stored) -------------------------------------
CREATE TABLE IF NOT EXISTS password_resets (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel     text   NOT NULL CHECK (channel IN ('email', 'sms', 'admin')),
  secret_hash text   NOT NULL,          -- email: sha256 of the link token; code: nonce$hmac
  attempts    integer NOT NULL DEFAULT 0,
  created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  revoked_at  timestamptz
);
CREATE INDEX IF NOT EXISTS ix_password_resets_user ON password_resets (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_password_resets_hash ON password_resets (secret_hash);

-- rate-limit log (keys are HMAC hashes: no phone, email or IP in clear)
CREATE TABLE IF NOT EXISTS auth_rate_events (
  id         bigserial PRIMARY KEY,
  key_hash   text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_auth_rate_events_key ON auth_rate_events (key_hash, created_at);

-- 7) record the migration ------------------------------------------------------------------------
DO $$ BEGIN
    IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'schema_migrations'
      AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 5 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 5)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''005_auth_identity_reset'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''005_auth_identity_reset'')';
  END IF;
END $$;

COMMIT;

/* ROLLBACK (run by hand only if needed; first make sure no two users share a phone, or step 3 fails):
BEGIN;
DROP TRIGGER IF EXISTS trg_users_require_customer_email ON users;
DROP FUNCTION IF EXISTS users_require_customer_email();
DROP TABLE IF EXISTS auth_rate_events;
DROP TABLE IF EXISTS password_resets;
DROP INDEX IF EXISTS ux_users_farmer_phone, ux_users_admin_phone, ux_users_customer_email, ix_users_phone;
ALTER TABLE users ADD CONSTRAINT users_phone_key UNIQUE (phone);
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_format;   -- email / session_version columns can stay
DELETE FROM schema_migrations WHERE version::text IN ('5', '005_auth_identity_reset');
COMMIT;
*/
