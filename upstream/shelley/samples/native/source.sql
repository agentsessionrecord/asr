PRAGMA journal_mode=WAL;
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    slug TEXT, -- human-readable identifier, can be null initially
    user_initiated BOOLEAN NOT NULL DEFAULT TRUE, -- FALSE for subagent/tool conversations
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
, cwd TEXT, archived BOOLEAN NOT NULL DEFAULT FALSE, parent_conversation_id TEXT REFERENCES conversations(conversation_id), model TEXT, conversation_options TEXT NOT NULL DEFAULT '{}', current_generation INTEGER NOT NULL DEFAULT 1, agent_working BOOLEAN NOT NULL DEFAULT FALSE, tags TEXT NOT NULL DEFAULT '[]', is_draft BOOLEAN NOT NULL DEFAULT FALSE, draft TEXT NOT NULL DEFAULT '', queued_messages TEXT NOT NULL DEFAULT '[]', turn_interrupted BOOLEAN NOT NULL DEFAULT FALSE, external_conversation_id TEXT, external_endpoint TEXT);
CREATE TABLE "messages" (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sequence_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    llm_data TEXT,
    user_data TEXT,
    usage_data TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    display_data TEXT,
    excluded_from_context BOOLEAN NOT NULL DEFAULT FALSE,
    generation INTEGER NOT NULL DEFAULT 1, llm_api_url TEXT, model_name TEXT, forked_from_message_id TEXT, user_email TEXT, other_usage_data TEXT, external_message_id TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);
INSERT INTO conversations(conversation_id,user_initiated,created_at,updated_at,cwd) VALUES ('synthetic-shelley',1,'2026-01-01 00:00:00','2026-01-01 00:00:00','/work/app');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('prompt','synthetic-shelley',0,'user','{"Role":0,"Content":[{"Type":2,"Text":"Read the synthetic item.\n"}]}','2026-01-01 00:00:00');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('call','synthetic-shelley',1,'agent','{"Role":1,"Content":[{"Type":3,"Thinking":"Check the item.\n","Signature":"synthetic-excluded-signature"},{"Type":5,"ID":"call-1","ToolName":"read","ToolInput":{"number":9007199254740993}}]}','2026-01-01 00:00:00');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('early-result','synthetic-shelley',2,'user','{"Role":0,"Content":[{"Type":6,"ToolUseID":"call-1","ToolError":false,"ToolResult":[{"Type":2,"Text":"partial"}]}]}','2026-01-01 00:00:00');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('notice','synthetic-shelley',3,'user','{"Role":0,"Content":[{"Type":2,"Text":"Continue.\n"}]}','2026-01-01 00:00:00');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('result','synthetic-shelley',4,'user','{"Role":0,"Content":[{"Type":6,"ToolUseID":"call-1","ToolError":true,"ToolResult":[{"Type":2,"Text":"failed\n"}]}]}','2026-01-01 00:00:00');
INSERT INTO messages(message_id,conversation_id,sequence_id,type,llm_data,created_at) VALUES ('reply','synthetic-shelley',5,'agent','{"Role":1,"Content":[{"Type":4,"Data":"opaque-synthetic-state"},{"Type":2,"Text":"Finished.\n"}]}','2026-01-01 00:00:00');
