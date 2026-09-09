#!/usr/bin/env python3
"""Create an isolated, synthetic DEV runtime on the retired host; no prod imports."""
import json
import hashlib
import hmac
import base64
import os
from pathlib import Path
import socket
import subprocess

if socket.gethostname() != 'stagingsw' or '10.9.10.53' not in subprocess.check_output(['hostname','-I'], text=True).split():
    raise SystemExit('Unexpected host')
base = Path('/srv/platform-dev/runtime')
base.mkdir(mode=0o700, exist_ok=True)
base.chmod(0o700)
secret_dir = base / 'secrets'
secret_dir.mkdir(mode=0o700, exist_ok=True)
secret_dir.chmod(0o700)
from remote_dev_credentials import initialize_credentials
secret = initialize_credentials()
generated = Path('/run/platform-dev-config')
subprocess.run(['sudo', '-n', 'install', '-d', '-o', 'halil', '-g', 'halil', '-m', '700', str(generated)], check=True)
if subprocess.check_output(['findmnt', '-T', str(generated), '-n', '-o', 'FSTYPE'], text=True).strip() != 'tmpfs':
    raise SystemExit('Generated DEV configuration must reside on tmpfs')

def write_runtime(name, content):
    # Secret delivery files are allowed only on the verified, private tmpfs above.
    # Establish restrictive mode before writing and refuse file symlinks.
    p = generated / name
    descriptor = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
    return str(p)

pg_image='postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'
kc_image='quay.io/keycloak/keycloak@sha256:4883630ef9db14031cde3e60700c9a9a8eaf1b5c24db1589d6a2d43de38ba2a9'
java_image='maven@sha256:8f6ac126f7810bb5549c4cd122d2bf0e9cda5bdeb0838aa928f09e779fd8bef8'
fga_image='openfga/openfga@sha256:e5891e4676e5a8b4659c010c50aabf487397844b18f66ef7510e5ad00935949f'
fga_state=json.loads((base/'openfga-state.json').read_text()) if (base/'openfga-state.json').exists() else {}
issuer='http://127.0.0.1:33081/realms/platform-dev'
jwks=issuer+'/protocol/openid-connect/certs'
realm={'realm':'platform-dev','enabled':True,'sslRequired':'none','registrationAllowed':False,
       'roles':{'realm':[{'name':'ADMIN'},{'name':'USER'},{'name':'VIEWER'}]},
       'clients':[{'clientId':'frontend','enabled':True,'publicClient':True,'standardFlowEnabled':True,'directAccessGrantsEnabled':True,
       'redirectUris':['http://127.0.0.1:33000/*'],'webOrigins':['http://127.0.0.1:33000'],
       'attributes':{'pkce.code.challenge.method':'S256'},
       'protocolMappers':[{'name':'dev-audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','config':{'included.client.audience':'frontend','access.token.claim':'true','id.token.claim':'false'}}]}],
       'users':[{'username':'developer','enabled':True,'emailVerified':True,'email':'developer@example.invalid','firstName':'DEV','lastName':'Developer','realmRoles':['ADMIN','USER'],
       'credentials':[{'type':'password','value':secret['developer'],'temporary':False}]},
       {'username':'viewer','enabled':True,'emailVerified':True,'email':'viewer@example.invalid','firstName':'DEV','lastName':'Viewer','realmRoles':['VIEWER'],
       'credentials':[{'type':'password','value':secret['developer'],'temporary':False}]}]}
realm_file=write_runtime('realm.json',json.dumps(realm))
write_runtime('postgres.env',f"POSTGRES_USER=platform\nPOSTGRES_DB=platform\nPOSTGRES_PASSWORD={secret['postgres']}\n")
write_runtime('keycloak.env',f"KC_BOOTSTRAP_ADMIN_USERNAME=dev-admin\nKC_BOOTSTRAP_ADMIN_PASSWORD={secret['keycloak_admin']}\nKC_DB=postgres\nKC_DB_URL=jdbc:postgresql://127.0.0.1:5432/keycloak\nKC_DB_USERNAME=platform\nKC_DB_PASSWORD={secret['postgres']}\nKC_HOSTNAME=http://127.0.0.1:33081\nKC_HEALTH_ENABLED=true\n")
write_runtime('openfga.env',f"OPENFGA_DATASTORE_ENGINE=postgres\nOPENFGA_DATASTORE_URI=postgres://platform:{secret['postgres']}@127.0.0.1:5432/openfga?sslmode=disable\nOPENFGA_HTTP_ADDR=127.0.0.1:34080\nOPENFGA_GRPC_ADDR=127.0.0.1:34081\nOPENFGA_PLAYGROUND_ENABLED=false\nOPENFGA_METRICS_ADDR=127.0.0.1:34112\n")
schemas=['auth_service','user_service','permission_service','variant_service','core_data_service','meeting_service','budget_service','notify','endpoint_admin_service','ethics_service','report_service']
init=write_runtime('postgres-init.sql',"CREATE ROLE platform_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '"+secret['postgres']+"';\nGRANT CREATE ON DATABASE platform TO platform_app;\nCREATE DATABASE keycloak;\n"+''.join(f'CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION platform_app;\n' for schema in schemas)+'CREATE DATABASE openfga;\n')
# The Postgres entrypoint reads this init script as its container user.
Path(init).chmod(0o644)
common={'network_mode':'host','restart':'unless-stopped','logging':{'driver':'local','options':{'max-size':'10m','max-file':'3'}}}
services={
 'openfga':{**common,'image':fga_image,'env_file':[str(generated/'openfga.env')],'command':['run'],'mem_limit':'512m','depends_on':{'postgres':{'condition':'service_healthy'}}},
 'postgres':{**common,'image':pg_image,'env_file':[str(generated/'postgres.env')],'command':['postgres','-c','listen_addresses=127.0.0.1'],'volumes':['dev-postgres:/var/lib/postgresql/data',f'{init}:/docker-entrypoint-initdb.d/01-dev.sql:ro'],'healthcheck':{'test':['CMD-SHELL','pg_isready -U platform -d platform'],'interval':'5s','timeout':'3s','retries':30},'mem_limit':'1g'},
 'keycloak':{**common,'image':kc_image,'env_file':[str(generated/'keycloak.env')],'command':['start-dev','--http-host=127.0.0.1','--http-port=33081','--import-realm'],'volumes':[f'{realm_file}:/opt/keycloak/data/import/platform-dev.json:ro'],'depends_on':{'postgres':{'condition':'service_healthy'}},'mem_limit':'1500m'}
}
# Keycloak reads the import file as uid 1000, not host root.
Path(realm_file).chmod(0o644)
override_path=base/'artifact-overrides.json'
overrides=json.loads(override_path.read_text()) if override_path.exists() else {}
ports={'api-gateway':8080,'auth-service':8088,'user-service':8089,'permission-service':8090,'variant-service':8091,'core-data-service':8092,'meeting-service':8097,'budget-service':8101,'notification-orchestrator':8093,'endpoint-admin-service':8098,'ethics-service':8099,'report-service':8095,'schema-service':8096}
for i,(svc,port) in enumerate(ports.items()):
    env={'SPRING_PROFILES_ACTIVE':'k8s','SERVER_ADDRESS':'127.0.0.1','SERVER_PORT':str(port),'MANAGEMENT_SERVER_ADDRESS':'127.0.0.1','MANAGEMENT_SERVER_PORT':str(34000+i),
      'SPRING_CONFIG_IMPORT':'','SPRING_CLOUD_VAULT_ENABLED':'false','EUREKA_CLIENT_ENABLED':'false','SPRING_CLOUD_DISCOVERY_ENABLED':'false',
      'SPRING_DATASOURCE_URL':'jdbc:postgresql://127.0.0.1:5432/platform','SPRING_DATASOURCE_USERNAME':'platform_app','SPRING_DATASOURCE_PASSWORD':secret['postgres'],
      'KEYCLOAK_ISSUER_URI':issuer,'KEYCLOAK_JWKS_URI':jwks,'SECURITY_JWT_ISSUER':issuer,'SECURITY_JWT_JWK_SET_URI':jwks,'SECURITY_JWT_USER_JWK_SET_URI':jwks,
      'SERVICE_AUTH_ISSUER':issuer,'SERVICE_AUTH_JWK_SET_URI':jwks,'SECURITY_JWT_AUDIENCE':'frontend','SECURITY_AUTH_ALLOWED_CLIENT_IDS':'frontend,admin-cli',
      'PERMISSION_SERVICE_BASE_URL':'http://127.0.0.1:8090','PERMISSION_AUDIT_MIRROR_BASE_URL':'http://127.0.0.1:8090','PERMISSION_SERVICE_INTERNAL_API_KEY':secret['service'],
      'PERMISSION_AUTHZ_USER_LOOKUP_BASE_URL':'http://127.0.0.1:8089','PERMISSION_AUTHZ_USER_TABLE':'user_service.users','SECURITY_INTERNAL_API_KEY_ENABLED':'true',
      'AUTO_PROVISION_ALLOWED_ISSUERS':issuer,'AUTO_PROVISION_ALLOW_LOCAL_KEYCLOAK':'true',
      'ERP_OPENFGA_ENABLED':'true','ERP_OPENFGA_API_URL':'http://127.0.0.1:34080','ERP_OPENFGA_STORE_ID':fga_state.get('store_id',''),'ERP_OPENFGA_MODEL_ID':fga_state.get('model_id',''),
      'REPORTS_DB_ENABLED':'false','SPRING_JPA_HIBERNATE_DDL_AUTO':'update','DB_POOL_MAX':'3','SPRING_JPA_SHOW_SQL':'false',
      'LOGGING_LEVEL_ORG_SPRINGFRAMEWORK_SECURITY':'INFO','LOGGING_LEVEL_ORG_HIBERNATE_SQL':'INFO','LOGGING_LEVEL_COM_EXAMPLE_USER':'INFO',
      'AUTH_IMPERSONATION_KEYCLOAK_TOKEN_URL':issuer+'/protocol/openid-connect/token','AUTH_SERVICE_URL':'http://127.0.0.1:8088','USER_SERVICE_URL':'http://127.0.0.1:8089','VARIANT_SERVICE_URL':'http://127.0.0.1:8091','CORE_DATA_URL':'http://127.0.0.1:8092',
      'NOTIFY_URL':'http://127.0.0.1:8093','ENDPOINT_ADMIN_SERVICE_URL':'http://127.0.0.1:8098','ETHICS_SERVICE_URL':'http://127.0.0.1:8099',
      'MEETING_SERVICE_URL':'http://127.0.0.1:8097','BUDGET_SERVICE_URL':'http://127.0.0.1:8101','REPORT_URL':'http://127.0.0.1:8095','SCHEMA_URL':'http://127.0.0.1:8096',
      'GATEWAY_CORS_ALLOWED_ORIGINS':'http://127.0.0.1:33000',
      'MEETING_AI_ENABLED':'false','MEETING_EVENTS_REDIS_ENABLED':'false','MEETING_REDIS_HEALTH_ENABLED':'false','MEETING_NOTIFY_ENABLED':'false',
      'MEETING_TRANSCRIPT_READ_ENABLED':'false','MEETING_ASSIGNEE_DIRECTORY_ENABLED':'false','MEETING_SESSION_ERASURE_ENABLED':'false',
      'PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_ENABLED':'true','PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_EMAILS':'developer@example.invalid',
      'PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_MAX_ATTEMPTS':'300',
      'PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_USER_TABLE':'user_service.users','PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_USER_TABLE_ID_SPACE':'canonical'}
    def derived(label):
        return base64.b64encode(hmac.new(secret['service'].encode(), label.encode(), hashlib.sha256).digest()).decode()
    if svc in {'notification-orchestrator','endpoint-admin-service','ethics-service'}:
        env['SPRING_JPA_HIBERNATE_DDL_AUTO']='validate'
    if svc in {'report-service','schema-service'}:
        reader_password='Aa1!'+derived('mssql-reader')
        env.update({'SPRING_DATASOURCE_URL':'jdbc:sqlserver://127.0.0.1:1433;databaseName=platform_dev;encrypt=true;trustServerCertificate=true;applicationIntent=ReadOnly',
                    'SPRING_DATASOURCE_USERNAME':'dev_reader','SPRING_DATASOURCE_PASSWORD':reader_password,
                    'SPRING_DATASOURCE_DRIVER_CLASS_NAME':'com.microsoft.sqlserver.jdbc.SQLServerDriver',
                    'REPORT_MSSQL_ENABLED':'true','REPORT_MSSQL_JDBC_URL':'jdbc:sqlserver://127.0.0.1:1433;databaseName=platform_dev;encrypt=true;trustServerCertificate=true;applicationIntent=ReadOnly',
                    'REPORT_MSSQL_USERNAME':'dev_reader','REPORT_MSSQL_PASSWORD':reader_password,
                    'REPORT_PG_URL':'jdbc:postgresql://127.0.0.1:5432/platform?currentSchema=report_service,user_service,public',
                    'REPORT_PG_USERNAME':'platform_app','REPORT_PG_PASSWORD':secret['postgres'],
                    'REPORT_REMOTE_EXECUTOR_USER_SERVICE_BASE_URL':'http://127.0.0.1:8089',
                    'REPORT_REMOTE_EXECUTOR_PERMISSION_SERVICE_BASE_URL':'http://127.0.0.1:8090'})
    if svc=='notification-orchestrator':
        env.update({'MANAGEMENT_TRACING_ENABLED':'false','NOTIFY_DB_SCHEMA':'notify','NOTIFY_AUTHZ_INTERNAL_API_KEY':secret['service'],
                    'NOTIFY_REDACTION_PEPPER':derived('notify-redaction'),'NOTIFY_DISPATCH_ENABLED':'false',
                    'NOTIFY_AUTHZ_PERMISSION_SERVICE_URL':'http://127.0.0.1:8090'})
    if svc=='endpoint-admin-service':
        env.update({'ENDPOINT_ADMIN_DB_SCHEMA':'endpoint_admin_service',
                    'ENDPOINT_ADMIN_ENROLLMENT_TOKEN_PEPPER':derived('endpoint-pepper'),
                    'ENDPOINT_ADMIN_SECRET_ENCRYPTION_KEY':derived('endpoint-encryption')})
    if svc=='ethics-service':
        env.update({'ETHICS_DB_SCHEMA':'ethics_service','ETHICS_PARTICIPANT_HANDLE_KEY':derived('ethics-handles'),
                    'ETHICS_IDENTITY_ACTIVE_KEY_ID':'v1','ETHICS_IDENTITY_KEY_V1':derived('ethics-identity'),
                    'ETHICS_PERMISSION_SERVICE_BASE_URL':'http://127.0.0.1:8090'})
    if svc!='api-gateway':
        schema={'notification-orchestrator':'notify','endpoint-admin-service':'endpoint_admin_service','ethics-service':'ethics_service'}.get(svc,svc.replace('-','_'))
        env['SPRING_JPA_PROPERTIES_HIBERNATE_DEFAULT_SCHEMA']=schema
        env['SPRING_FLYWAY_DEFAULT_SCHEMA']=schema
        env['SPRING_FLYWAY_SCHEMAS']=schema
        env[svc.split('-')[0].upper()+'_DB_SCHEMA']=schema
    jars=list(Path('/srv/platform-dev/repos/platform-backend',svc,'target').glob('*.jar'))
    jars=[p for p in jars if not p.name.endswith(('-sources.jar','-javadoc.jar'))]
    if len(jars)!=1:raise SystemExit(f'Expected one executable jar for {svc}')
    if svc in overrides:
        candidate=Path(overrides[svc]['path']).resolve(strict=True)
        if not candidate.is_relative_to(Path('/srv/platform-dev/artifacts')):
            raise SystemExit('Artifact override must remain in the DEV artifact directory')
        if hashlib.sha256(candidate.read_bytes()).hexdigest()!=overrides[svc]['sha256']:
            raise SystemExit('Artifact override digest mismatch')
        jars=[candidate]
    env_file=write_runtime(svc+'.env',''.join(f'{k}={v}\n' for k,v in env.items()))
    services[svc]={**common,'image':java_image,'env_file':[env_file],'command':['java','-Xms64m','-Xmx512m','-jar','/app/app.jar'],'volumes':[f'{jars[0]}:/app/app.jar:ro'],'mem_limit':'1g','depends_on':{'postgres':{'condition':'service_healthy'}}}
sql_env=write_runtime('mssql.env','ACCEPT_EULA=Y\nMSSQL_PID=Developer\nMSSQL_MEMORY_LIMIT_MB=2048\nMSSQL_SA_PASSWORD=Aa1!'+derived('mssql-admin')+'\n')
services['mssql']={'image':'mcr.microsoft.com/mssql/server@sha256:97b448857967be55e005424a660056fe6d51814435804dc07e8f79f028bab5fb',
                   'restart':'unless-stopped','ports':['127.0.0.1:1433:1433'],'mem_limit':'3g',
                   'env_file':[sql_env],'volumes':['dev-mssql:/var/opt/mssql']}
services['mailpit']={'image':'axllent/mailpit@sha256:98b916bd3c8d61f7633a52d3ea2f58d00620cb01ca57ab59edde68c347a95365',
                     'restart':'unless-stopped','ports':['127.0.0.1:1025:1025','127.0.0.1:8025:8025'],'mem_limit':'256m'}
compose_text=json.dumps({'name':'platform-dev-runtime','services':services,'volumes':{'dev-postgres':{},'dev-mssql':{}}},indent=2)
if any(value in compose_text for value in secret.values()):
    raise SystemExit('Refusing to persist inline DEV credential material')
(base/'compose.json').write_text(compose_text)
(base/'compose.json').chmod(0o600)
print('DEV_COMPOSE_PREPARED',len(services),'services; encrypted credential store; generated configuration on tmpfs')
