#!/usr/bin/env python3
"""Ensure synthetic DEV tenant/subscriber claims using the realm admin API."""
import json,urllib.request,urllib.parse,sys,subprocess
from pathlib import Path
sys.path.insert(0,"/srv/platform-dev/ops")
from remote_dev_credentials import load_credentials,require_host
require_host();secret=load_credentials();base="http://127.0.0.1:33081"
def req(path,data=None,method="GET",token=None,form=False):
 headers={}
 if token:headers["Authorization"]="Bearer "+token
 if data is not None:
  headers["Content-Type"]="application/x-www-form-urlencoded" if form else "application/json"
  data=(urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
 with urllib.request.urlopen(urllib.request.Request(base+path,data=data,method=method,headers=headers),timeout=30) as r:
  b=r.read();return json.loads(b) if b else None
token=req("/realms/master/protocol/openid-connect/token",dict(grant_type="password",client_id="admin-cli",username="dev-admin",password=secret["keycloak_admin"]),"POST",form=True)["access_token"]
profile=req("/admin/realms/platform-dev/users/profile",token=token)
if not any(a["name"]=="platformUserId" for a in profile["attributes"]):
 profile["attributes"].append({"name":"platformUserId","displayName":"Platform user ID","permissions":{"view":["admin"],"edit":["admin"]}})
 req("/admin/realms/platform-dev/users/profile",profile,"PUT",token)
users=req("/admin/realms/platform-dev/users?username=developer&exact=true",token=token)
assert len(users)==1
user=users[0]
row=subprocess.check_output(["docker","--host","unix:///run/platform-dev/docker.sock","exec","platform-dev-runtime-postgres-1","psql","-U","platform","-d","platform","-Atc","SELECT id::text || '|' || kc_subject FROM user_service.users WHERE email='developer@example.invalid' AND deleted_at IS NULL;"],text=True).strip().split("|")
assert len(row)==2 and row[0].isdigit() and row[1]==user["id"]
attrs=user.get("attributes",{});attrs["platformUserId"]=[row[0]]
req("/admin/realms/platform-dev/users/"+user["id"],dict(user,attributes=attrs,firstName="DEV",lastName="Developer",email="developer@example.invalid",emailVerified=True),"PUT",token)
assert req("/admin/realms/platform-dev/users/"+user["id"],token=token)["attributes"]["platformUserId"]==[row[0]]
client=req("/admin/realms/platform-dev/clients?clientId=frontend",token=token)[0]["id"]
path="/admin/realms/platform-dev/clients/"+client+"/protocol-mappers/models"
mappers=[
 {"name":"dev-user-id","protocol":"openid-connect","protocolMapper":"oidc-usermodel-attribute-mapper","config":{"user.attribute":"platformUserId","claim.name":"userId","jsonType.label":"long","access.token.claim":"true","id.token.claim":"true"}},
 {"name":"dev-org","protocol":"openid-connect","protocolMapper":"oidc-hardcoded-claim-mapper","config":{"claim.name":"org_id","claim.value":"00000000-0000-4000-8000-000000000053","jsonType.label":"String","access.token.claim":"true","id.token.claim":"true"}},
 {"name":"dev-subscriber","protocol":"openid-connect","protocolMapper":"oidc-usermodel-property-mapper","config":{"user.attribute":"id","claim.name":"subscriberId","jsonType.label":"String","access.token.claim":"true","id.token.claim":"true"}}
]
existing={x["name"]:x for x in req(path,token=token)}
for m in mappers:
 if m["name"] in existing:
  ident=existing[m["name"]]["id"];req(path+"/"+ident,dict(m,id=ident),"PUT",token)
 else:req(path,m,"POST",token)
read={x["name"]:x for x in req(path,token=token)}
assert all(all(read[m["name"]]["config"].get(k)==v for k,v in m["config"].items()) for m in mappers)
Path("/srv/platform-dev/evidence/identity-mappers.json").write_text(json.dumps({"realm":"platform-dev","client":"frontend","mappers":[m["name"] for m in mappers],"readback":True}))
print("DEV org/subscriber mapper configuration readback passed")
