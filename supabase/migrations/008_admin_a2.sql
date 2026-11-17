-- 008: Admin A2 — complaint workflow (assign, internal notes, more statuses), order cancel reason.
-- Safe to re-run. Nothing is deleted. Rollback block at the end.
BEGIN;

-- 1) complaints: Submitted(open) / Under review(in_review) / In progress / Resolved / Rejected / Closed -----------
ALTER TABLE complaints DROP CONSTRAINT IF EXISTS complaints_status_check;
ALTER TABLE complaints ADD CONSTRAINT complaints_status_check
  CHECK (status IN ('open', 'in_review', 'in_progress', 'resolved', 'rejected', 'closed'));
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS assigned_to bigint REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_complaints_status ON complaints (status, created_at DESC);

-- internal staff notes (never shown to the user); notes are not edited or deleted
CREATE TABLE IF NOT EXISTS complaint_notes (
  id           bigserial PRIMARY KEY,
  complaint_id bigint NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
  author_id    bigint REFERENCES users(id) ON DELETE SET NULL,
  note         text NOT NULL CHECK (length(note) BETWEEN 2 AND 2000),
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_complaint_notes ON complaint_notes (complaint_id, created_at);

-- 2) orders: why an admin cancelled it ----------------------------------------------------------------------
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancel_reason text;

-- 3) record the migration -------------------------------------------------------------------------------------
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 8 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 8)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''008_admin_a2'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''008_admin_a2'')';
  END IF;
END $$;

COMMIT;

/* ROLLBACK (by hand only; first move complaints in 'in_progress'/'rejected' back to an old status):
BEGIN;
UPDATE complaints SET status = 'in_review' WHERE status = 'in_progress';
UPDATE complaints SET status = 'closed' WHERE status = 'rejected';
ALTER TABLE complaints DROP CONSTRAINT complaints_status_check;
ALTER TABLE complaints ADD CONSTRAINT complaints_status_check CHECK (status IN ('open', 'in_review', 'resolved', 'closed'));
DROP TABLE IF EXISTS complaint_notes;
DELETE FROM schema_migrations WHERE version::text IN ('8', '008_admin_a2');
COMMIT;
*/
