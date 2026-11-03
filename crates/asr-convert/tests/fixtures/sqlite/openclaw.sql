-- Authored native storage example. All content is synthetic.
PRAGMA user_version=37;
CREATE TABLE session_windows(session_id TEXT PRIMARY KEY,session_key TEXT,started_at INTEGER,ended_at INTEGER,previous_session_id TEXT,reason TEXT);
CREATE TABLE session_nodes(session_key TEXT PRIMARY KEY,entry_json TEXT);
CREATE TABLE transcript_events(session_id TEXT,seq INTEGER,event_json TEXT,event_zstd BLOB,event_utf8_bytes INTEGER);
INSERT INTO session_windows VALUES('example','agent:main:example',1000,NULL,NULL,'initial');
INSERT INTO session_nodes VALUES('agent:main:example','{"sessionId":"example","permissionMode":"ask","createdActor":{"type":"human","id":"example-person"}}');
INSERT INTO transcript_events VALUES('example',1,'{"type":"session","id":"example","cwd":"/work/app","timestamp":"2026-01-01T00:00:00Z"}',NULL,NULL);
INSERT INTO transcript_events VALUES('example',2,'{"type":"message","id":"prompt","message":{"role":"user","content":"Read a file."}}',NULL,NULL);
INSERT INTO transcript_events VALUES('example',3,'{"type":"message","id":"assistant","timestamp":"2026-01-01T00:00:01Z","message":{"role":"assistant","responseId":"response-1","model":"requested-model","responseModel":"served-model","content":[{"type":"text","text":"Reading."},{"type":"toolCall","id":"read-1","name":"read","arguments":{"path":"test.txt"}}],"usage":{"input":10,"cacheRead":2,"output":3,"reasoning":0}}}',NULL,NULL);
INSERT INTO transcript_events VALUES('example',4,'{"type":"message","id":"result","timestamp":"2026-01-01T00:00:02Z","message":{"role":"toolResult","toolCallId":"read-1","isError":false,"content":[{"type":"text","text":"hello"}]}}',NULL,NULL);
CREATE TABLE operator_approvals(approval_id TEXT PRIMARY KEY,source_session_id TEXT,status TEXT,decision TEXT,resolved_at_ms INTEGER);
INSERT INTO operator_approvals VALUES('decision','example','allowed','allow-once',2500);
INSERT INTO transcript_events VALUES('example',5,'{"type":"message","id":"approval-result","message":{"role":"toolResult","isError":false,"content":[{"type":"text","text":"Allowed."}],"details":{"approvalId":"decision"}}}',NULL,NULL);
