#!/usr/bin/env python3
"""Correlate DEV Docker state, cgroups, artifacts and actual HTTP behavior."""
import hashlib,json,os,socket,subprocess,sys,urllib.request
from pathlib import Path
assert socket.gethostname()=="stagingsw"
D=["docker","--host","unix:///run/platform-dev/docker.sock"]
compose=json.loads(Path("/srv/platform-dev/runtime/compose.json").read_text())
out={"containers":[],"http":[],"checks":[]}
def check(name,ok):
 out["checks"].append({"name":name,"ok":bool(ok)})
for service,cfg in compose["services"].items():
 name=compose["name"]+"-"+service+"-1"
 c=json.loads(subprocess.check_output(D+["inspect",name]))[0]
 s=c["State"]; pid=s["Pid"]
 cg=Path(f"/proc/{pid}/cgroup")
 owned=pid>0 and cg.exists() and c["Id"] in cg.read_text()
 image=json.loads(subprocess.check_output(D+["image","inspect",cfg["image"]]))[0]["Id"]
 check(service+":running-owned",s["Running"] and owned)
 check(service+":image",c["Image"]==image)
 mounts=[]
 for m in c["Mounts"]:
  src=Path(m["Source"]).resolve()
  safe=str(src).startswith(("/srv/platform-dev/","/run/platform-dev-config/"))
  check(service+":local-mount:"+m["Destination"],safe)
  entry={"source":str(src),"destination":m["Destination"],"type":m["Type"]}
  if m["Destination"]=="/app/app.jar":entry["sha256"]=hashlib.sha256(src.read_bytes()).hexdigest()
  mounts.append(entry)
 out["containers"].append({"service":service,"id":c["Id"],"pid":pid,"running":s["Running"],"owned":owned,"image":c["Image"],"mounts":mounts})
ports=[33000,33001,33002,33004,33005,33006,33007,33008,33009,33010,33011]
urls=[(str(p),f"http://127.0.0.1:{p}/"+("" if p==33000 else "remoteEntry.js")) for p in ports]
urls += [("oidc","http://127.0.0.1:33081/realms/platform-dev/.well-known/openid-configuration")]
for svc,cfg in compose["services"].items():
 env={}
 for f in cfg.get("env_file",[]):
  env.update(dict(line.split("=",1) for line in Path(f).read_text().splitlines() if "=" in line))
 if "MANAGEMENT_SERVER_PORT" in env:
  urls.append((svc,f"http://127.0.0.1:{env['MANAGEMENT_SERVER_PORT']}/actuator/health"))
for name,url in urls:
 try:
  with urllib.request.urlopen(url,timeout=12) as r:
   body=r.read(); status=r.status
   ok=status==200 and (b'"status":"UP"' in body if "/actuator/" in url else True)
 except Exception as e: status=type(e).__name__;ok=False
 out["http"].append({"name":name,"status":status});check("http:"+name,ok)
out["passed"]=all(c["ok"] for c in out["checks"])
dest=Path(sys.argv[1] if len(sys.argv)>1 else "/srv/platform-dev/evidence/runtime-verification.json")
dest.write_text(json.dumps(out,indent=2));dest.chmod(0o600)
print(json.dumps({"passed":out["passed"],"containers":len(out["containers"]),"http":out["http"],"failed":[c["name"] for c in out["checks"] if not c["ok"]]}))
sys.exit(0 if out["passed"] else 1)
