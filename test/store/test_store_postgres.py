# -*- coding: utf-8 -*-
# test/store/test_store_postgres.py
'''
PostgreSQL-specific tests, gated on ``ONYA_TEST_PG_DSN`` (PostgreSQL >= 17). These cover
paths outside the shared conformance matrix: the ``reachable()`` recursive-CTE helper over
``onya_edge_hop``, and (on PostgreSQL >= 19 only, gated additionally on ``ONYA_TEST_PG19_DSN``)
the SQL/PGQ ``graph_table`` escape hatch with a known-answer friend-of-friend pattern.

    ONYA_TEST_PG_DSN=postgresql://... pytest -s test/store/test_store_postgres.py
'''

import os

import pytest

from onya.store import GraphQueryStore, connect
from onya.store.postgres import reachable
from store_helpers import DOCHEADER, parse

pytestmark = pytest.mark.integration

PG_DSN = os.environ.get('ONYA_TEST_PG_DSN')
PG19_DSN = os.environ.get('ONYA_TEST_PG19_DSN')

FRIENDS = DOCHEADER.replace('http://e.o/doc', 'http://e.o/friends') + '''
# A [Person]

* knows -> B

# B [Person]

* knows -> C

# C [Person]

* knows -> D

# D [Person]

* name: Dee
'''
KNOWS = 'https://schema.org/knows'
GNAME = 'http://e.o/friends'


@pytest.mark.skipif(not PG_DSN, reason='set ONYA_TEST_PG_DSN to run PostgreSQL tests')
async def test_reachable_bounded_transitive():
    async with await connect(PG_DSN) as store:
        await store._reset_for_tests()
        await store.put(GNAME, parse(FRIENDS))
        r1 = {str(x) for x in await reachable(store, GNAME, 'http://e.o/A', KNOWS, 1)}
        r2 = {str(x) for x in await reachable(store, GNAME, 'http://e.o/A', KNOWS, 2)}
        r3 = {str(x) for x in await reachable(store, GNAME, 'http://e.o/A', KNOWS, 3)}
        assert r1 == {'http://e.o/B'}
        assert r2 == {'http://e.o/B', 'http://e.o/C'}
        assert r3 == {'http://e.o/B', 'http://e.o/C', 'http://e.o/D'}
        await store._reset_for_tests()


@pytest.mark.skipif(not PG19_DSN, reason='set ONYA_TEST_PG19_DSN to run SQL/PGQ tests')
async def test_pgq_friend_of_friend():
    async with await connect(PG19_DSN) as store:
        await store._reset_for_tests()
        if not isinstance(store, GraphQueryStore):  # a 19 server without SQL/PGQ (19rc1 has none) opens without it
            pytest.skip('this PostgreSQL server has no SQL/PGQ (CREATE PROPERTY GRAPH)')
        await store.put(GNAME, parse(FRIENDS))
        rows = await store.graph_table(
            '''
            SELECT * FROM GRAPH_TABLE (onya_base
                MATCH (a IS resource WHERE a.id = $1)
                      -[e IS asserted WHERE e.label = $2]->(b IS resource)
                      -[f IS asserted WHERE f.label = $2]->(c IS resource)
                COLUMNS (c.id AS fof))
            ''',
            'http://e.o/A', KNOWS)
        assert {r[0] for r in rows} == {'http://e.o/C'}   # A knows B knows C
        await store._reset_for_tests()


@pytest.mark.skipif(not PG_DSN, reason='set ONYA_TEST_PG_DSN to run PostgreSQL tests')
async def test_from_pool_leaves_the_callers_pool_open_and_finds_search():
    asyncpg = pytest.importorskip('asyncpg')
    from onya.store.postgres import PostgresStore
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    try:
        async with await PostgresStore.from_pool(pool) as store:
            assert store.has_trgm  # the same bootstrap connect() does
            await store.put(GNAME, parse(FRIENDS))
            assert len([n async for n in store.names()]) >= 1
            await store._reset_for_tests()
        assert await pool.fetchval('SELECT 1') == 1  # closing the store did not close the caller's pool
    finally:
        await pool.close()


@pytest.mark.skipif(not PG_DSN, reason='set ONYA_TEST_PG_DSN to run PostgreSQL tests')
async def test_from_pool_can_hand_the_pool_over():
    asyncpg = pytest.importorskip('asyncpg')
    from onya.store.postgres import PostgresStore
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    async with await PostgresStore.from_pool(pool, owns_pool=True):
        pass
    with pytest.raises(asyncpg.InterfaceError):  # closed with the store
        await pool.fetchval('SELECT 1')


@pytest.mark.skipif(not PG_DSN, reason='set ONYA_TEST_PG_DSN to run PostgreSQL tests')
async def test_connect_passes_pool_options_to_asyncpg():
    async with await connect(PG_DSN, max_size=3) as store:  # min_size follows, as asyncpg's own default would not
        assert store._pool.get_max_size() == 3
