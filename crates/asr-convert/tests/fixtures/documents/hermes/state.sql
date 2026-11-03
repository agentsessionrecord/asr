CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, started_at REAL, ended_at REAL, cwd TEXT, input_tokens INTEGER, output_tokens INTEGER, actual_cost_usd REAL);
CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, timestamp REAL, finish_reason TEXT, reasoning_content TEXT, active INTEGER, compacted INTEGER);
INSERT INTO sessions VALUES('hermes-sample','cli','parent:three',1793448000,1793448010,'/work/app',0,7,0.0);
INSERT INTO messages VALUES(1,'hermes-sample','user','Read it.',NULL,NULL,NULL,1793448001,NULL,NULL,1,0);
INSERT INTO messages VALUES(2,'hermes-sample','assistant','Reading.','[{"id":"read-1","function":{"name":"read_file","arguments":"{\"path\":\"src/parser.py\"}"}}]',NULL,NULL,1793448000,'tool_calls','Inspect content first.',0,1);
INSERT INTO messages VALUES(3,'hermes-sample','tool','  ready
',NULL,'read-1','read_file',1793448002,'success',NULL,1,0);
