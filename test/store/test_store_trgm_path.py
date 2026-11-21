# -*- coding: utf-8 -*-
# test/store/test_store_trgm_path.py
'''
`pg_trgm` installed in a schema the connection's `search_path` excludes (Supabase puts it in `extensions`).
#90: `has_trgm` must never claim indexed search the connection can't run. #92: when the role may use that schema,
indexed search qualifies the names, instead of giving up. Each test makes a fresh database, so it needs a role that
may `CREATE DATABASE`; it is skipped otherwise.

    ONYA_TEST_PG_DSN=postgresql://... pytest -s test/store/test_store_trgm_path.py
'''

import contextlib
import logging
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

from onya.store.postgres import PostgresStore
from store_helpers import parse

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.environ.get('ONYA_TEST_PG_DSN'), reason='ONYA_TEST_PG_DSN not set')]

SRC = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# ada [Person]
* name: Ada Lovelace

# bo [Person]
* name: Bo Peep
'''
NAME = 'http://e.o/doc'


@contextlib.asynccontextmanager
async def fresh_db(*, trgm=True, ext_schema='extensions'):
    '''A fresh database with `pg_trgm` in schema `ext_schema` (unless `trgm` is False) and an empty `tenant` schema.'''
    import asyncpg  # lazy, like the other PostgreSQL tests: the default install doesn't have it
    dsn, name = os.environ['ONYA_TEST_PG_DSN'], 'onya_trgm_' + uuid.uuid4().hex[:8]
    admin = await asyncpg.connect(dsn)
    try:
        await admin.execute(f'CREATE DATABASE {name}')
    except asyncpg.PostgresError as e:
        await admin.close()
        pytest.skip(f'this role cannot CREATE DATABASE: {e}')
    try:
        c = await asyncpg.connect(dsn, database=name)
        try:
            await c.execute(f'CREATE SCHEMA "{ext_schema}"; CREATE SCHEMA tenant')
            if trgm:
                await c.execute(f'CREATE EXTENSION pg_trgm WITH SCHEMA "{ext_schema}"')
        finally:
            await c.close()
        yield dsn, name
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def db():
    async with fresh_db() as d:
        yield d


async def store_on(db, search_path, *, dsn=None, **kw):
    import asyncpg
    base, name = db
    pool = await asyncpg.create_pool(dsn or base, database=name, min_size=1, max_size=2,
                                     server_settings={'search_path': search_path})
    return await PostgresStore.from_pool(pool, owns_pool=True, **kw)


async def scalar(db, sql, *, search_path=None, settings=()):
    import asyncpg
    dsn, name = db
    c = await asyncpg.connect(dsn, database=name, server_settings={'search_path': search_path} if search_path else None)
    try:
        for s in settings:
            await c.execute(s)
        return await c.fetchval(sql)
    finally:
        await c.close()


def summary(hits):
    return [(str(h.node_id), h.tier, round(h.score, 6)) for h in hits]


async def test_extension_off_the_path_is_used_qualified_and_indexed(db):
    async with await store_on(db, 'tenant') as store:
        assert store.has_trgm is True and store._trgm_schema == 'extensions'  # not on the path: qualified
        await store.put(NAME, parse(SRC))
        hits = await store.search(NAME, 'ada lovelac')  # an unqualified query raised `operator does not exist`
        assert [(h[0], h[1]) for h in summary(hits)] == [('http://e.o/ada', 'fuzzy')]
        # the same data, the same query, with the schema on the path (unqualified): same hits, same scores
        async with await store_on(db, 'tenant, extensions') as on_path:
            assert on_path._trgm_schema == ''
            assert summary(await on_path.search(NAME, 'ada lovelac')) == summary(hits)
            assert summary(await on_path.search(NAME, 'bo')) == summary(await store.search(NAME, 'bo'))
    assert await scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'onya_assertion_value_trgm'") == 1


async def test_the_planner_uses_the_index_for_the_qualified_operator(db):
    '''The index was built with the schema-qualified operator class; a qualified query must still be served by it.'''
    import asyncpg
    async with await store_on(db, 'tenant') as store:
        await store.put(NAME, parse(SRC))
    dsn, name = db
    c = await asyncpg.connect(dsn, database=name, server_settings={'search_path': 'tenant'})
    try:
        await c.execute('SET enable_seqscan = off')  # two rows: the planner would otherwise scan, whatever the index
        rows = await c.fetch("EXPLAIN SELECT 1 FROM onya_assertion WHERE kind = 'P' "
                             "AND onya_normalize(value) OPERATOR(extensions.%) 'ada lovelac'")
    finally:
        await c.close()
    assert 'onya_assertion_value_trgm' in '\n'.join(r[0] for r in rows)


async def test_detecting_without_ensuring_follows_the_connections_path_too(db):
    async with await store_on(db, 'tenant, extensions'):  # provisioned once, by a role that sees the extension
        pass
    async with await store_on(db, 'tenant', ensure=False) as store:  # an application role that doesn't
        assert store.has_trgm is True and store._trgm_schema == 'extensions'
        await store.put(NAME, parse(SRC))
        assert [str(h.node_id) for h in await store.search(NAME, 'bo pee')] == ['http://e.o/bo']
    async with await store_on(db, 'tenant, extensions', ensure=False) as store:
        assert store.has_trgm is True and store._trgm_schema == ''


async def test_no_pg_trgm_at_all_means_in_process_search(db, caplog):
    async with await store_on(db, 'tenant'):  # provisions the core tables (and, on the path, the extension)
        pass
    await scalar(db, 'DROP EXTENSION pg_trgm CASCADE')  # and now it is installed nowhere
    with caplog.at_level(logging.INFO):
        store = await store_on(db, 'tenant, extensions', ensure=False)
    async with store:
        assert store.has_trgm is False and store._trgm_schema is None  # nothing to qualify, so it must not claim to
        await store.put(NAME, parse(SRC))
        assert [str(h.node_id) for h in await store.search(NAME, 'ada lovelac')] == ['http://e.o/ada']


async def test_a_role_without_usage_on_the_schema_falls_back_and_says_why(db, caplog):
    import asyncpg
    dsn, name = db
    role, password = 'onya_nousage_' + uuid.uuid4().hex[:8], 'pw' + uuid.uuid4().hex[:8]
    admin = await asyncpg.connect(dsn, database=name)
    try:
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
    except asyncpg.PostgresError as e:
        await admin.close()
        pytest.skip(f'this role cannot CREATE ROLE: {e}')
    try:
        await admin.execute(f'REVOKE ALL ON SCHEMA extensions FROM PUBLIC; GRANT ALL ON SCHEMA tenant TO {role}')
        parts = urlsplit(dsn)
        host = parts.hostname + (f':{parts.port}' if parts.port else '')
        as_role = urlunsplit(parts._replace(netloc=f'{role}:{password}@{host}'))
        with caplog.at_level(logging.INFO):
            store = await store_on(db, 'tenant', dsn=as_role)
        async with store:
            assert store.has_trgm is False
            assert any('no USAGE' in r.getMessage() and "'extensions'" in r.getMessage() for r in caplog.records)
            await store.put(NAME, parse(SRC))
            assert [str(h.node_id) for h in await store.search(NAME, 'ada lovelac')] == ['http://e.o/ada']
    finally:
        await admin.execute(f'DROP OWNED BY {role}; DROP ROLE {role}')  # its tables and grants, in this database
        await admin.close()


async def test_a_schema_name_that_needs_quoting_is_quoted():
    async with fresh_db(ext_schema='Trgm Ext') as db:
        async with await store_on(db, 'tenant') as store:
            assert store.has_trgm is True and store._trgm_schema == '"Trgm Ext"'  # an identifier, never raw text
            await store.put(NAME, parse(SRC))
            assert [str(h.node_id) for h in await store.search(NAME, 'ada lovelac')] == ['http://e.o/ada']
        assert await scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'onya_assertion_value_trgm'") == 1
