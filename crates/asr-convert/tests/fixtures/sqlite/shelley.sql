-- Authored native storage example. All content is synthetic.
CREATE TABLE conversations(conversation_id TEXT PRIMARY KEY,slug TEXT,parent_conversation_id TEXT);
CREATE TABLE messages(message_id TEXT PRIMARY KEY,conversation_id TEXT,sequence_id INTEGER,type TEXT,llm_data TEXT,user_data TEXT,usage_data TEXT,forked_from_message_id TEXT);
INSERT INTO conversations VALUES('example','Example',NULL);
INSERT INTO messages VALUES('prompt','example',1,'user','{"Role":0,"Content":[{"Type":2,"Text":"Read a file."}]}',NULL,NULL,NULL);
INSERT INTO messages VALUES('assistant','example',2,'agent','{"Role":1,"Content":[{"Type":2,"Text":"Reading."},{"Type":5,"ID":"read-1","ToolName":"read","ToolInput":{"path":"test.txt"}},{"Type":6,"ToolUseID":"read-1","ToolError":false,"ToolResult":[{"Type":2,"Text":"hello"}]}],"EndOfTurn":true}',NULL,'{"input_tokens":10,"cache_read_input_tokens":3,"output_tokens":2,"cost_usd":0.0,"model":"served-model"}',NULL);
