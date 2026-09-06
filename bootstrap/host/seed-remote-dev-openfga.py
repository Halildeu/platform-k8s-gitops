#!/usr/bin/env python3
"""Seed and verify the existing synthetic DEV OpenFGA fixtures on the retired host."""
from pathlib import Path
import subprocess,json,urllib.request
import socket
if socket.gethostname() != 'stagingsw': raise SystemExit('Unexpected host')
b=Path('/srv/platform-dev/runtime'); repo=Path('/srv/platform-dev/repos/platform-k8s-gitops');base='http://127.0.0.1:34080'
def req(path,payload):
 with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=15) as r:return json.load(r)
state_file=b/'openfga-state.json'
if state_file.exists():state=json.loads(state_file.read_text())
else:
 store=req('/stores',{'name':'platform-dev'})['id']
 model=json.loads(subprocess.check_output(['python3',str(repo/'bootstrap/local-fixtures/openfga/render_model_json.py'),str(repo/'bootstrap/local-fixtures/openfga/model.fga')],text=True))
 model_id=req('/stores/'+store+'/authorization-models',model)['authorization_model_id']
 state={'store_id':store,'model_id':model_id};state_file.write_text(json.dumps(state));state_file.chmod(0o600)
fixture=json.loads((repo/'bootstrap/local-fixtures/openfga/tuples.json').read_text())
try:req('/stores/'+state['store_id']+'/write',{'authorization_model_id':state['model_id'],'writes':{'tuple_keys':fixture['tuples']}})
except urllib.error.HTTPError as e:
 if e.code!=400:raise
passed=0
for x in fixture['smoke_checks']:
 r=req('/stores/'+state['store_id']+'/check',{'authorization_model_id':state['model_id'],'tuple_key':x['check']})
 assert r['allowed']==x['expected']
 passed+=1
print('OPENFGA_ALLOW_DENY_FIXTURES_PASS',passed)
