-- Authored native storage example. All content is synthetic.
CREATE TABLE chat_sessions(id TEXT PRIMARY KEY,title TEXT,messages_json TEXT,created_at INTEGER);
CREATE TABLE subagent_conversations(session_id TEXT,tool_call_id TEXT,messages_json TEXT);
INSERT INTO chat_sessions VALUES('example','Example','[{"id":"prompt","role":"user","content":"Read a file."},{"id":"assistant","role":"assistant","content":"Reading.","tool_calls":[{"id":"read-1","function":{"name":"read","arguments":"{\"path\":\"test.txt\"}"}}]},{"id":"result","role":"tool","tool_call_id":"read-1","content":"hello","is_error":false}]',1000);
INSERT INTO subagent_conversations VALUES('example','child-call','[{"role":"assistant","content":"Child result."}]');
