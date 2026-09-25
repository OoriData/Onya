# sql/examples/regenerate.py
'''
Rewrite postgres-schema.sql from the canonical DDL in `onya.store`. Maintainer convenience only;
the output is an example (see its header), not a supported migration path.

    python sql/examples/regenerate.py
'''

from pathlib import Path

from onya.__about__ import __version__
from onya.store._relational import POSTGRES, SCHEMA_VERSION, SKELETON_HASH_VERSION, ddl_statements
from onya.store.postgres import _NORMALIZE_FN

HEADER = f'''-- Onya PostgreSQL store schema — EXAMPLE ONLY (generated from onya {__version__})
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
'''

SECTIONS = [
    ('Core tables and indexes', [s + ';' for s in ddl_statements(POSTGRES)]),
    ('Version keys (onya checks these on open and refuses a store built by a different algorithm)', [
        "INSERT INTO onya_meta (key, value) VALUES"
        f" ('schema_version', '{SCHEMA_VERSION}'), ('skeleton_hash_version', '{SKELETON_HASH_VERSION}')"
        ' ON CONFLICT (key) DO NOTHING;',
    ]),
    ('Search (SearchStore). Without pg_trgm, search still works, ranked in-process and unindexed', [
        _NORMALIZE_FN.strip() + ';',
        'CREATE EXTENSION IF NOT EXISTS pg_trgm;',
        'CREATE INDEX IF NOT EXISTS onya_assertion_value_trgm ON onya_assertion'
        " USING gin (onya_normalize(value) gin_trgm_ops) WHERE kind = 'P';",
    ]),
    ('Example grants for an application role that only reads and writes data (adjust the role name)', [
        '-- GRANT USAGE ON SCHEMA public TO onya_app;',
        '-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO onya_app;',
        '-- (Identity columns need no separate sequence grant; this is exactly what onya\'s integration test uses.)',
    ]),
]


def main() -> None:
    out = [HEADER]
    for title, stmts in SECTIONS:
        out.append(f'\n-- {title}\n')
        out.extend(stmts)
    path = Path(__file__).with_name('postgres-schema.sql')
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(f'wrote {path}')


if __name__ == '__main__':
    main()
