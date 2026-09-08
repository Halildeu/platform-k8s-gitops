#!/usr/bin/env python3
"""Provision only synthetic data in the isolated DEV SQL Server."""
import sys,subprocess,os,hmac,hashlib,base64,json
from pathlib import Path
sys.path.insert(0,"/srv/platform-dev/ops")
from remote_dev_credentials import load_credentials,require_host
require_host();secret=load_credentials()
def password(label):return "Aa1!"+base64.b64encode(hmac.new(secret["service"].encode(),label.encode(),hashlib.sha256).digest()).decode()
D=["docker","--host","unix:///run/platform-dev/docker.sock"]
c=json.loads(subprocess.check_output(D+["inspect","platform-dev-runtime-mssql-1"]))[0]
assert c["Config"]["Labels"]["com.docker.compose.project"]=="platform-dev-runtime"
env=dict(os.environ,SQLCMDPASSWORD=password("mssql-admin"))
sql="""IF DB_ID('platform_dev') IS NULL CREATE DATABASE platform_dev;
GO
IF SUSER_ID('dev_reader') IS NULL CREATE LOGIN dev_reader WITH PASSWORD = '"""+password("mssql-reader")+"""';
GO
USE platform_dev;
GO
IF SCHEMA_ID('dev_fixture') IS NULL EXEC('CREATE SCHEMA dev_fixture');
IF OBJECT_ID('dev_fixture.projects') IS NULL CREATE TABLE dev_fixture.projects(id int PRIMARY KEY, name nvarchar(100) NOT NULL);
IF OBJECT_ID('dev_fixture.tasks') IS NULL CREATE TABLE dev_fixture.tasks(id int PRIMARY KEY, project_id int NOT NULL REFERENCES dev_fixture.projects(id), title nvarchar(100) NOT NULL);
IF NOT EXISTS(SELECT 1 FROM dev_fixture.projects WHERE id=1) INSERT dev_fixture.projects VALUES(1,N'Synthetic DEV project');
IF NOT EXISTS(SELECT 1 FROM dev_fixture.tasks WHERE id=1) INSERT dev_fixture.tasks VALUES(1,1,N'Synthetic DEV task');
IF USER_ID('dev_reader') IS NULL CREATE USER dev_reader FOR LOGIN dev_reader;
ALTER ROLE db_datareader ADD MEMBER dev_reader;
GRANT VIEW DEFINITION TO dev_reader;
GO
"""
def sqlcmd(user,text,env):
 return subprocess.run(D+["exec","-i","--env","SQLCMDPASSWORD",c["Id"],"/opt/mssql-tools18/bin/sqlcmd","-S","localhost","-U",user,"-C","-b"],input=text.encode(),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
r=sqlcmd("sa",sql,env)
if r.returncode:raise SystemExit("DEV SQL setup failed; no SQL/credential output emitted")
env["SQLCMDPASSWORD"]=password("mssql-reader")
read=sqlcmd("dev_reader","USE platform_dev; SELECT count(*) FROM dev_fixture.projects;",env)
deny=sqlcmd("dev_reader","USE platform_dev; INSERT dev_fixture.projects VALUES (99,N'Should be denied');",env)
assert read.returncode==0 and deny.returncode!=0
Path("/srv/platform-dev/evidence/mssql-fixture.json").write_text(json.dumps({"synthetic":True,"reader_select":True,"reader_insert_denied":True,"tables":2,"foreign_keys":1}))
print("DEV SQL: synthetic tables + FK, read-only application login; INSERT denied")
