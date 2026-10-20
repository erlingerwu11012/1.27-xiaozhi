ALTER TABLE ai_person_material ADD COLUMN user_tokens INT NOT NULL DEFAULT 0, ADD COLUMN token_version SMALLINT NOT NULL DEFAULT 0;
CREATE TABLE ai_archive_retired_event (
 account_id BIGINT NOT NULL, event_id VARCHAR(128) NOT NULL,
 PRIMARY KEY(account_id,event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX ix_material_recent_agent ON ai_person_material(account_id,user_id,generation,agent_id,kind,id);
