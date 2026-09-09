#!/usr/bin/env python3
"""Seed and verify the existing synthetic DEV OpenFGA fixtures on the retired host."""
from pathlib import Path
import subprocess,json,urllib.request,hashlib
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
# The full canonical model adds meeting/notification types without changing
# existing explicit-scope semantics. Refuse any alteration to existing types.
canonical=Path('/srv/platform-dev/repos/platform-backend/backend/openfga')
expanded=json.loads(subprocess.check_output(['python3',str(canonical/'render_model_json.py'),str(canonical/'model.fga')],text=True))
with urllib.request.urlopen(base+'/stores/'+state['store_id']+'/authorization-models/'+state['model_id']) as response:
 current=json.load(response)['authorization_model']
old_types={x['type']:x for x in current['type_definitions']}
new_types={x['type']:x for x in expanded['type_definitions']}
assert all(value==new_types.get(key) for key,value in old_types.items()), 'Existing DEV model semantics changed'
previous_state=dict(state)
if old_types!=new_types:
 state['model_id']=req('/stores/'+state['store_id']+'/authorization-models',expanded)['authorization_model_id']
state['source_sha256']=hashlib.sha256((canonical/'model.fga').read_bytes()).hexdigest()
fixture=json.loads((repo/'bootstrap/local-fixtures/openfga/tuples.json').read_text())
try:req('/stores/'+state['store_id']+'/write',{'authorization_model_id':state['model_id'],'writes':{'tuple_keys':fixture['tuples']}})
except urllib.error.HTTPError as e:
 if e.code!=400:raise
passed=0
for x in fixture['smoke_checks']:
 r=req('/stores/'+state['store_id']+'/check',{'authorization_model_id':state['model_id'],'tuple_key':x['check']})
 assert r['allowed']==x['expected']
 passed+=1
if state!=previous_state:
 (b/'openfga-state-previous.json').write_text(json.dumps(previous_state))
 state_file.write_text(json.dumps(state));state_file.chmod(0o600)
print('OPENFGA_ALLOW_DENY_FIXTURES_PASS',passed,'TYPES',len(new_types))
