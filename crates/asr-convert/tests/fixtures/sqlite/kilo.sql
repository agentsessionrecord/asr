-- Authored native storage example. All content is synthetic.
CREATE TABLE session(id TEXT PRIMARY KEY,directory TEXT,title TEXT,time_created INTEGER,version TEXT,parent_id TEXT,permission TEXT);
CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,time_created INTEGER,data TEXT);
CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,data TEXT);
INSERT INTO session VALUES('example','/work/app','Example',1000,'synthetic-storage-v1',NULL,NULL);
INSERT INTO message VALUES('prompt','example',1000,'{"role":"user"}');
INSERT INTO message VALUES('assistant','example',2000,'{"role":"assistant","modelID":"requested-model","providerID":"example-provider","tokens":{"input":10,"output":5,"reasoning":3,"cache":{"read":2}}}');
INSERT INTO part VALUES('p1','prompt','example','{"type":"text","text":"Edit the file.\n"}');
INSERT INTO part VALUES('p2','assistant','example','{"type":"text","text":"Editing.\n"}');
INSERT INTO part VALUES('p3','assistant','example','{"type":"tool","callID":"edit-1","tool":"edit","state":{"status":"completed","input":{"filePath":"/work/app/test.txt","oldString":"old\n","newString":"new\n"},"output":"Edit applied.","metadata":{"diff":"--- a/test.txt\n+++ b/test.txt\n@@ -1 +1 @@\n-old\n+new\n"}}}');
