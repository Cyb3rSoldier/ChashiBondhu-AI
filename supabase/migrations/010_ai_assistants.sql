-- 010: AI assistants (Fosholi / Dr. Krishi): each conversation belongs to ONE assistant.
-- Old conversations stay as 'classic'. Safe to re-run.
BEGIN;
ALTER TABLE ai_conversations ADD COLUMN IF NOT EXISTS assistant text NOT NULL DEFAULT 'classic';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_conversations_assistant_check') THEN
    ALTER TABLE ai_conversations ADD CONSTRAINT ai_conversations_assistant_check
      CHECK (assistant IN ('classic', 'fosholi', 'drkrishi'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_ai_conv_user_assistant ON ai_conversations (user_id, assistant, updated_at DESC);
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 10 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 10)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''010_ai_assistants'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''010_ai_assistants'')';
  END IF;
END $$;
COMMIT;
/* ROLLBACK: ALTER TABLE ai_conversations DROP COLUMN assistant; DELETE FROM schema_migrations WHERE version::text IN ('10','010_ai_assistants'); */
