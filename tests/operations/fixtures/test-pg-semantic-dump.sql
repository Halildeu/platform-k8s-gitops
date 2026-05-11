--
-- Minimal pg_dumpall-shaped fixture for TPG-RESET semantic backup guard.
-- This is not a restorable dump; it contains only the CREATE markers required
-- by scripts/operations/check_test_pg_stateful_guard.py.
--

CREATE DATABASE variants_db;
\connect variants_db
CREATE SCHEMA variant_service;
CREATE TABLE variant_service.themes (
    id bigint PRIMARY KEY
);

CREATE DATABASE reports_db;
\connect reports_db
CREATE SCHEMA data_access;
CREATE TABLE data_access.scope (
    id bigint PRIMARY KEY
);

CREATE DATABASE openfga;
\connect openfga
CREATE TABLE public.tuple (
    store text NOT NULL
);
CREATE TABLE public.authorization_model (
    id text PRIMARY KEY
);
