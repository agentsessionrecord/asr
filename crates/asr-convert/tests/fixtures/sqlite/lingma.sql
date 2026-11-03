-- Authored native storage example. All content is synthetic.
CREATE TABLE chat_record(session_id TEXT,request_id TEXT,chat_prompt TEXT,summary TEXT,error_result TEXT,gmt_create INTEGER,extra TEXT);
INSERT INTO chat_record VALUES('example','request-1','Explain the file.','The answer summary.',NULL,1700000000000,'{"context":1}');
