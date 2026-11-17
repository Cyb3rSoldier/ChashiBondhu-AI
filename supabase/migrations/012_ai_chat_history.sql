-- 012: chat history for Fosholi / Dr. Krishi (sidebar: search, rename, delete; diagnosis cards after reload).
-- Safe to re-run. Only adds two nullable columns and one index; no data is changed.
--   ai_conversations.hidden_at : "delete" hides a chat from the farmer. The rows stay, so admin feedback
--                                 statistics (ai_feedback -> ai_messages) are not lost.
--   ai_messages.payload        : the checked, structured photo diagnosis (crop, problem, steps ...) so the
--                                 cards can be drawn again. The photo itself is still never stored.
ALTER TABLE public.ai_conversations ADD COLUMN IF NOT EXISTS hidden_at timestamptz;
ALTER TABLE public.ai_messages      ADD COLUMN IF NOT EXISTS payload   jsonb;

CREATE INDEX IF NOT EXISTS ix_ai_conv_visible
    ON public.ai_conversations (user_id, assistant, updated_at DESC) WHERE hidden_at IS NULL;

DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 12 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 12)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''012_ai_chat_history'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''012_ai_chat_history'')';
  END IF;
END $$;
/* ROLLBACK: DROP INDEX ix_ai_conv_visible; ALTER TABLE ai_messages DROP COLUMN payload;
   ALTER TABLE ai_conversations DROP COLUMN hidden_at; DELETE FROM schema_migrations WHERE version::text IN ('12','012_ai_chat_history'); */
