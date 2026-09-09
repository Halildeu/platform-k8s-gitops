#!/usr/bin/env python3
"""Grant the synthetic developer role through permission-service, never direct tuples."""
import sys,json,urllib.request,urllib.parse,base64,time
from pathlib import Path
sys.path.insert(0,"/srv/platform-dev/ops")
from remote_dev_credentials import load_credentials,require_host
require_host()
r=urllib.request.Request("http://127.0.0.1:33081/realms/platform-dev/protocol/openid-connect/token",data=urllib.parse.urlencode(dict(grant_type="password",client_id="frontend",username="developer",password=load_credentials()["developer"])).encode())
token=json.load(urllib.request.urlopen(r))["access_token"]
claims=json.loads(base64.urlsafe_b64decode(token.split(".")[1]+"=="))
assert claims["preferred_username"]=="developer" and int(claims["userId"])>0
def req(path,data=None,method="GET"):
 headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
 r=urllib.request.Request("http://127.0.0.1:8090/api/v1"+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers=headers)
 with urllib.request.urlopen(r,timeout=30) as response:
  raw=response.read();return json.loads(raw) if raw else None
roles=req("/roles?pageSize=100")["items"]
role=next((r for r in roles if r["name"]=="REMOTE_DEV"),None)
if role is None:role=req("/roles",{"name":"REMOTE_DEV","description":"Synthetic isolated DEV developer journeys; #3582"},"POST")
rid=str(role["id"])
permissions=[{"type":"MODULE","key":key,"grant":"MANAGE"} for key in ["MEETING","endpoint-admin","ENDPOINT_ADMIN"]]
permissions.append({"type":"REPORT","key":"users-overview","grant":"VIEW"})
req("/roles/"+rid+"/granules",{"permissions":permissions},"PUT")
req("/roles/"+rid+"/members",{"userIds":[int(claims["userId"])]},"POST")
got=req("/roles/"+rid+"/granules")
assert sorted(got["granules"],key=lambda x:x["key"])==sorted(permissions,key=lambda x:x["key"])
Path("/srv/platform-dev/evidence/developer-role.json").write_text(json.dumps({"role_id":rid,"role":"REMOTE_DEV","canonical_api":True,"granules_readback":True,"grants":permissions},indent=2))
print("DEV role/membership configured via permission-service; granules read back")
