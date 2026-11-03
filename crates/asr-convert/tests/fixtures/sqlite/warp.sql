-- Authored native storage example. All content is synthetic.
CREATE TABLE agent_conversations(conversation_id TEXT PRIMARY KEY,conversation_data TEXT);
CREATE TABLE agent_tasks(conversation_id TEXT,task_id TEXT,task BLOB);
INSERT INTO agent_conversations VALUES('example','{"agent_name":"Example"}');
INSERT INTO agent_tasks VALUES('example','task-1',X'2a180a0670726f6d7074120e0a0c5265616420612066696c652e2a200a0463616c6c22180a06726561642d31120e0a0c63617420746573742e7478742a1d0a06726573756c742a130a06726561642d3112090a0568656c6c6f2a002a100a057265706c791a070a05446f6e652e');
