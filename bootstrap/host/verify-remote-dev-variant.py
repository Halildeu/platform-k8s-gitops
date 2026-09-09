import sys,json,urllib.request,urllib.parse,urllib.error,uuid
from pathlib import Path
sys.path.insert(0,"/srv/platform-dev/ops")
from remote_dev_credentials import load_credentials
password=load_credentials()["developer"]
def token():
 req=urllib.request.Request("http://127.0.0.1:33081/realms/platform-dev/protocol/openid-connect/token",data=urllib.parse.urlencode(dict(grant_type="password",client_id="frontend",username="developer",password=password)).encode())
 return json.load(urllib.request.urlopen(req))["access_token"]
def call(path,method="GET",data=None,bearer=None):
 headers={"Content-Type":"application/json"}
 if bearer:headers["Authorization"]="Bearer "+bearer
 req=urllib.request.Request("http://127.0.0.1:33000"+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers=headers)
 try:
  with urllib.request.urlopen(req,timeout=30) as r:
   raw=r.read();return r.status,json.loads(raw) if raw else None
 except urllib.error.HTTPError as e:return e.code,None
t=token(); grid="remote-dev-proof-"+str(uuid.uuid4())
status,body=call("/api/v1/variants?gridId="+grid,bearer=t)
result={"list_status":status}
if status==200:
 status,body=call("/api/v1/variants","POST",{"gridId":grid,"name":"Remote DEV persistence proof","state":{"columns":[]},"schemaVersion":1},t)
 result["create_status"]=status
 if status==201:
  ident=body["id"]
  try:
   status,listed=call("/api/v1/variants?gridId="+grid,bearer=token())
   result["new_session_readback"]=status==200 and any(str(x["id"])==str(ident) for x in listed["items"])
  finally:result["delete_status"]=call("/api/v1/variants/"+str(ident),"DELETE",bearer=t)[0]
  status,listed=call("/api/v1/variants?gridId="+grid,bearer=token());result["cleanup_readback"]=status==200 and len(listed["items"])==0
result["anonymous_status"]=call("/api/v1/variants?gridId="+grid)[0]
result["passed"]=result.get("new_session_readback") and result.get("cleanup_readback") and result["anonymous_status"]==401
Path("/srv/platform-dev/evidence/variant-e2e.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result))
sys.exit(0 if result["passed"] else 1)
