-- Authored native storage example. All content is synthetic.
CREATE TABLE sessions(id TEXT PRIMARY KEY,working_directory TEXT,main_chain_id INTEGER,agent_mode TEXT);
CREATE TABLE message_nodes(session_id TEXT,node_id INTEGER,parent_node_id INTEGER,chat_message TEXT,metadata TEXT,created_at INTEGER);
CREATE TABLE tool_call_state(session_id TEXT,tool_call_id TEXT,tool_call_json TEXT,tool_call_update_json TEXT);
INSERT INTO sessions VALUES('example','/work/app',3,'agent');
INSERT INTO message_nodes VALUES('example',1,NULL,'{"role":"user","message_id":"prompt","content":"Read a file.","metadata":{"is_user_input":true}}','{}',1);
INSERT INTO message_nodes VALUES('example',2,1,'{"role":"assistant","message_id":"assistant","content":"Reading.","metadata":{"request_id":"request-1","metrics":{"input_tokens":10,"output_tokens":2}},"tool_calls":[{"id":"read-1","function":{"name":"read","arguments":"{\"path\":\"test.txt\"}"}}]}','{}',2);
INSERT INTO message_nodes VALUES('example',3,2,'{"role":"tool","tool_call_id":"read-1","content":"hello"}','{}',3);
INSERT INTO tool_call_state VALUES('example','read-1','{}','{"status":"completed","_meta":{"terminal_exit":{"exit_code":0}}}');
