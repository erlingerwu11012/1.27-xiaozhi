-- Additive migration. Check information_schema first; do not run twice.
ALTER TABLE ai_person_material ADD COLUMN recall_allowed BOOLEAN NOT NULL DEFAULT TRUE;
