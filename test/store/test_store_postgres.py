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
        await store.put(GNAME, parse(FRIENDS))
        assert isinstance(store, GraphQueryStore)
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
