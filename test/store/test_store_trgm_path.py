# -*- coding: utf-8 -*-
# test/store/test_store_trgm_path.py
'''
#90: `has_trgm` means the trigram operators resolve on the connection's own `search_path`, not just that `pg_trgm`
exists somewhere in the database (Supabase installs it in schema `extensions`). Each test makes a fresh database, so
it needs a role that may `CREATE DATABASE`; it is skipped otherwise.

    ONYA_TEST_PG_DSN=postgresql://... pytest -s test/store/test_store_trgm_path.py
'''

import logging
import os
import uuid

import asyncpg
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


@pytest.fixture
async def db():
    '''A fresh database with `pg_trgm` in schema `extensions`, and an empty `tenant` schema.'''
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
            await c.execute('CREATE SCHEMA extensions; CREATE SCHEMA tenant; '
                            'CREATE EXTENSION pg_trgm WITH SCHEMA extensions')
        finally:
            await c.close()
        yield dsn, name
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
        await admin.close()


async def store_on(db, search_path, **kw):
    dsn, name = db
    pool = await asyncpg.create_pool(dsn, database=name, min_size=1, max_size=2,
                                     server_settings={'search_path': search_path})
    return await PostgresStore.from_pool(pool, owns_pool=True, **kw)


async def trgm_indexes(db):
    dsn, name = db
    c = await asyncpg.connect(dsn, database=name)
    try:
        return await c.fetchval("SELECT count(*) FROM pg_indexes WHERE indexname = 'onya_assertion_value_trgm'")
    finally:
        await c.close()


async def test_extension_in_a_schema_off_the_path_means_in_process_search(db, caplog):
    with caplog.at_level(logging.INFO):
        store = await store_on(db, 'tenant')
    async with store:
        assert store.has_trgm is False  # was True: pg_extension found it, though its operators aren't reachable
        assert any("'extensions'" in r.getMessage() and 'search_path' in r.getMessage() for r in caplog.records)
        await store.put(NAME, parse(SRC))
        hits = await store.search(NAME, 'ada lovelac')  # raised `operator does not exist: unknown % text`
        assert [str(h.node_id) for h in hits] == ['http://e.o/ada']
    assert await trgm_indexes(db) == 0  # the index could not have been made, and nothing pretends it was


async def test_with_the_schema_on_the_path_search_is_indexed(db):
    async with await store_on(db, 'tenant, extensions') as store:
        assert store.has_trgm is True
        await store.put(NAME, parse(SRC))
        assert [str(h.node_id) for h in await store.search(NAME, 'ada lovelac')] == ['http://e.o/ada']
    assert await trgm_indexes(db) == 1


async def test_detecting_without_ensuring_follows_the_connections_path_too(db):
    async with await store_on(db, 'tenant, extensions'):  # provisioned once, by a role that sees the extension
        pass
    async with await store_on(db, 'tenant', ensure=False) as store:  # an application role that doesn't
        assert store.has_trgm is False
        await store.put(NAME, parse(SRC))
        assert [str(h.node_id) for h in await store.search(NAME, 'bo pee')] == ['http://e.o/bo']
    async with await store_on(db, 'tenant, extensions', ensure=False) as store:
        assert store.has_trgm is True
