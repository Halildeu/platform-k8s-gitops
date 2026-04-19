-- ADR-0002 test PG init — same DB schema as prod (test isolation)
-- Farklı instance; prod ile cross-contamination yok.
-- Test default scale-to-zero (ADR §5.1) — up edilirse bu init çalışır.

CREATE USER platform WITH PASSWORD 'CHANGE_ME_TEST';
CREATE USER keycloak_user WITH PASSWORD 'CHANGE_ME_TEST';
CREATE USER openfga WITH PASSWORD 'CHANGE_ME_TEST';

CREATE DATABASE auth_db OWNER platform;
CREATE DATABASE users_db OWNER platform;
CREATE DATABASE variants_db OWNER platform;
CREATE DATABASE core_db OWNER platform;
CREATE DATABASE reports_db OWNER platform;
CREATE DATABASE schemas_db OWNER platform;
CREATE DATABASE permission_db OWNER platform;
CREATE DATABASE openfga OWNER openfga;
CREATE DATABASE keycloak OWNER keycloak_user;

-- CHANGE_ME_TEST placeholder — test Vault'tan gerçek password ESO sync sonrası.
