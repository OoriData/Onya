-- Onya PostgreSQL store schema — EXAMPLE ONLY (generated from onya 0.5.0)
--
-- Onya creates and upgrades this schema itself whenever a store is opened (DDL only for what's
-- missing, so a data-only role can open a store provisioned by this script), so most deployments
-- never need this file. It's here as a starting point for setups where schema changes go through
-- your own migration tooling (Alembic, Flyway, sqitch, a DBA). Adapt it to your environment: it
-- makes no assumptions about schemas, owners, roles, or search_path beyond the defaults, and
-- carries no compatibility promise across onya versions. Every statement is idempotent
-- (IF NOT EXISTS / ON CONFLICT DO NOTHING / CREATE OR REPLACE), so re-running it is harmless.
--
-- Not included: the SQL/PGQ property graphs onya creates on PostgreSQL >= 19 (see
-- onya.store.postgres._ensure_pgq).
--
-- Prefixes for graphs stored before prefix persistence can't be recovered by SQL (they were never
-- recorded). To backfill from the source document, put a prefixes-only graph, which adds prefix
-- rows and leaves the data untouched:
--
--     from onya.graph import graph
--     from onya.serial import literate
--     await store.put(name, graph(prefixes=literate.read(open(src)).graph.prefixes))


-- Core tables and indexes

CREATE TABLE IF NOT EXISTS onya_meta ( key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS onya_graph ( graph_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS onya_ident ( ident_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, graph_pk BIGINT NOT NULL REFERENCES onya_graph(graph_pk) ON DELETE CASCADE, id TEXT NOT NULL, UNIQUE (graph_pk, id));
CREATE TABLE IF NOT EXISTS onya_graph_prefix ( graph_pk BIGINT NOT NULL REFERENCES onya_graph(graph_pk) ON DELETE CASCADE, prefix TEXT NOT NULL, namespace TEXT NOT NULL, PRIMARY KEY (graph_pk, prefix));
CREATE TABLE IF NOT EXISTS onya_node ( node_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ident_pk BIGINT NOT NULL UNIQUE REFERENCES onya_ident(ident_pk) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS onya_node_type ( node_pk BIGINT NOT NULL REFERENCES onya_node(node_pk) ON DELETE CASCADE, type_iri TEXT NOT NULL, PRIMARY KEY (node_pk, type_iri));
CREATE TABLE IF NOT EXISTS onya_assertion ( assertion_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, graph_pk BIGINT NOT NULL REFERENCES onya_graph(graph_pk) ON DELETE CASCADE, kind CHAR(1) NOT NULL CHECK (kind IN ('E','P')), origin_node BIGINT REFERENCES onya_node(node_pk) ON DELETE CASCADE, origin_assertion BIGINT REFERENCES onya_assertion(assertion_pk) ON DELETE CASCADE, label TEXT NOT NULL, target_ident BIGINT REFERENCES onya_ident(ident_pk), value TEXT, ident_pk BIGINT UNIQUE REFERENCES onya_ident(ident_pk), interp TEXT, skeleton_hash BYTEA NOT NULL, CHECK ((origin_node IS NULL) <> (origin_assertion IS NULL)), CHECK ((kind = 'E' AND target_ident IS NOT NULL AND value IS NULL)     OR (kind = 'P' AND value IS NOT NULL AND target_ident IS NULL)));
CREATE TABLE IF NOT EXISTS onya_edge_hop ( assertion_pk BIGINT PRIMARY KEY REFERENCES onya_assertion(assertion_pk) ON DELETE CASCADE, source_ident BIGINT NOT NULL REFERENCES onya_ident(ident_pk) ON DELETE CASCADE, target_ident BIGINT NOT NULL REFERENCES onya_ident(ident_pk) ON DELETE CASCADE, label TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS onya_assertion_origin_node ON onya_assertion (graph_pk, origin_node, label);
CREATE INDEX IF NOT EXISTS onya_assertion_origin_assertion ON onya_assertion (graph_pk, origin_assertion, label);
CREATE INDEX IF NOT EXISTS onya_assertion_target ON onya_assertion (graph_pk, target_ident);
CREATE UNIQUE INDEX IF NOT EXISTS onya_assertion_skeleton ON onya_assertion (graph_pk, skeleton_hash, COALESCE(interp, '')) WHERE ident_pk IS NULL;
CREATE INDEX IF NOT EXISTS onya_edge_hop_source ON onya_edge_hop (source_ident, label);

-- Version keys (onya checks these on open and refuses a store built by a different algorithm)

INSERT INTO onya_meta (key, value) VALUES ('schema_version', '1'), ('skeleton_hash_version', '1') ON CONFLICT (key) DO NOTHING;

-- Search (SearchStore). Without pg_trgm, search still works, ranked in-process and unindexed

CREATE OR REPLACE FUNCTION onya_normalize(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT btrim(regexp_replace(lower(t), '[^[:alnum:]]+', ' ', 'g')) $$;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS onya_assertion_value_trgm ON onya_assertion USING gin (onya_normalize(value) gin_trgm_ops) WHERE kind = 'P';

-- Example grants for an application role that only reads and writes data (adjust the role name)

-- GRANT USAGE ON SCHEMA public TO onya_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO onya_app;
-- (Identity columns need no separate sequence grant; this is exactly what onya's integration test uses.)
