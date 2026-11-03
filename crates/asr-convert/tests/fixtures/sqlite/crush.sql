-- Authored native storage example. All content is synthetic.
CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,created_at INTEGER,prompt_tokens INTEGER,completion_tokens INTEGER,cost REAL);
CREATE TABLE messages(id TEXT PRIMARY KEY,session_id TEXT,role TEXT,parts TEXT,created_at INTEGER,model TEXT,is_summary_message INTEGER);
CREATE TABLE files(id TEXT PRIMARY KEY,session_id TEXT,path TEXT,content TEXT,version INTEGER);
INSERT INTO sessions VALUES('example','Check empty input',1000,10,3,0.0);
INSERT INTO messages VALUES('prompt','example','user','[{"type":"text","data":{"text":"Read test.txt.\n"}}]',1000,NULL,0);
INSERT INTO messages VALUES('assistant','example','assistant','[{"type":"reasoning","data":{"thinking":"Check the file."}},{"type":"tool_call","data":{"id":"read-1","name":"read_file","input":"{\"path\":\"test.txt\",\"n\":9007199254740993}"}}]',2000,NULL,0);
INSERT INTO messages VALUES('result','example','tool','[{"type":"tool_result","data":{"tool_call_id":"read-1","content":"hello\n","is_error":false}}]',3000,NULL,0);
INSERT INTO messages VALUES('reply','example','assistant','[{"type":"text","data":{"text":"Read it.\n"}},{"type":"finish","data":{"reason":"end_turn"}}]',4000,NULL,0);
INSERT INTO files VALUES('file-1','example','/work/test.txt','hello
',1);
