-- Faz 17.1 PG fixture seed — NOT_FOR_PROD. Mac k3d-dev cluster.
-- Dev-seed.sh postgres host-bridge üzerinden bu SQL'i çalıştırır.

-- ===== Databases =====
-- (dev compose stack tarafında CREATE DATABASE yapılır; bu script ondan sonra)

-- ===== auth_db seed =====
\c auth_db;

-- Session table (auth-service uses Spring Session JDBC)
-- Spring Boot startup kendisi oluşturur; sadece bir örnek seed user kayıtlı tutuluyorsa:

-- (Dev: users Keycloak realm'inde, PG'de sadece session/audit tables)

-- ===== user_service.users =====
\c user_db;

INSERT INTO user_service.users (id, email, keycloak_sub, created_at, updated_at)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'dev@localtest.me', 'dev-keycloak-sub-1', now(), now()),
  ('00000000-0000-0000-0000-000000000002', 'viewer@localtest.me', 'viewer-keycloak-sub-2', now(), now())
ON CONFLICT (email) DO NOTHING;

-- ===== permission_db seed (scoped allow for admin) =====
\c permission_db;

-- Scopes
INSERT INTO scopes (scope_type, ref_id) VALUES
  ('company', 'dev'),
  ('project', 'dev-local'),
  ('variant', 'sample-variant-1')
ON CONFLICT DO NOTHING;

-- Permissions (scoped allow seed for dev@localtest.me)
INSERT INTO user_permission_scope (user_id, permission_id, scope_id)
SELECT
  (SELECT id FROM users WHERE email = 'dev@localtest.me'),
  (SELECT id FROM permissions WHERE code = p.code),
  (SELECT id FROM scopes WHERE scope_type = s.st AND ref_id = s.ri)
FROM (VALUES
  ('VARIANT_READ', 'variant', 'sample-variant-1'),
  ('VARIANT_WRITE', 'variant', 'sample-variant-1'),
  ('PROJECT_READ', 'project', 'dev-local'),
  ('COMPANY_ADMIN', 'company', 'dev')
) AS p(code, st, ri)
ON CONFLICT DO NOTHING;

-- Role assignment: dev@localtest.me → ADMIN
INSERT INTO user_role_assignments (user_id, role_id)
SELECT
  (SELECT id FROM users WHERE email = 'dev@localtest.me'),
  (SELECT id FROM roles WHERE name = 'ADMIN')
ON CONFLICT DO NOTHING;

-- viewer@localtest.me → VIEWER (restricted)
INSERT INTO user_role_assignments (user_id, role_id)
SELECT
  (SELECT id FROM users WHERE email = 'viewer@localtest.me'),
  (SELECT id FROM roles WHERE name = 'VIEWER')
ON CONFLICT DO NOTHING;

-- ===== reports_db seed =====
\c reports_db;

-- Minimal sample for frontend rendering
INSERT INTO reports (key, title, category, source_schema, created_at)
VALUES
  ('dev-sample-report', 'Dev Sample Report', 'Dev', 'workcube_mikrolink_dev', now())
ON CONFLICT (key) DO NOTHING;

\echo 'Local dev PG seed complete.';
