-- ADR-0002 prod PG init — fresh instance DB + role create
-- Runs ONCE on first container startup (postgres-entrypoint docker init pattern).
-- Idempotent-safe: CREATE IF NOT EXISTS pattern yerine koşul kontrolü
-- (postgres:16-alpine entrypoint default skip-if-data-exists davranışı)

-- Roles (ownership separation)
CREATE USER platform WITH PASSWORD 'CHANGE_ME_PROD';
CREATE USER keycloak_user WITH PASSWORD 'CHANGE_ME_PROD';
CREATE USER openfga WITH PASSWORD 'CHANGE_ME_PROD';

-- Databases (one per service, owner = platform unless otherwise)
CREATE DATABASE auth_db OWNER platform;
CREATE DATABASE users_db OWNER platform;
CREATE DATABASE variants_db OWNER platform;
CREATE DATABASE core_db OWNER platform;
CREATE DATABASE reports_db OWNER platform;
CREATE DATABASE schemas_db OWNER platform;
CREATE DATABASE permission_db OWNER platform;
CREATE DATABASE openfga OWNER openfga;
CREATE DATABASE keycloak OWNER keycloak_user;

-- NOT: Gerçek password rotation sonrası bu init script etkisiz;
-- CHANGE_ME_PROD placeholder yalnız fresh bootstrap içindir.
-- Rotation: bkz docs/day-2-governance.md §2.1.
