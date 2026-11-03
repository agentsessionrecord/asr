-- Authored native storage example. All content is synthetic.
CREATE TABLE sessions(id TEXT PRIMARY KEY,name TEXT,working_dir TEXT,goose_mode TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY,message_id TEXT,session_id TEXT,role TEXT,content_json TEXT,created_timestamp INTEGER,metadata_json TEXT);
CREATE TABLE usage_ledger(id INTEGER PRIMARY KEY,session_id TEXT,created_timestamp INTEGER,model TEXT,input_tokens INTEGER,output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,cost REAL,cost_source TEXT);
INSERT INTO sessions VALUES('example','Example','/work/app','auto');
INSERT INTO messages VALUES(1,'prompt','example','user','[{"type":"text","text":"Read a file."}]',1,'{"steer":true}');
INSERT INTO messages VALUES(2,'assistant','example','assistant','[{"type":"text","text":"Reading."},{"type":"toolRequest","id":"read-1","toolCall":{"value":{"name":"read","arguments":{"path":"test.txt"}}}}]',2,'{}');
INSERT INTO messages VALUES(3,'result','example','user','[{"type":"toolResponse","id":"read-1","toolResult":{"status":"success","value":{"isError":false,"content":[{"type":"text","text":"hello"}]}}}]',3,'{}');
INSERT INTO usage_ledger VALUES(1,'example',2,'served-model',10,3,2,NULL,0.0,'estimated');
INSERT INTO messages VALUES(900,'decision','example','user','[{"type":"actionRequired","data":{"actionType":"toolConfirmationResponse","permission":"allow_once"}}]',4,'{}');
