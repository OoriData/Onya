# -*- coding: utf-8 -*-
# test/store/test_store_assertions.py
'''
Behavioral tests for the ``AssertionStore`` capability (fine-grained access without
materializing the whole graph). Runs against every backend from the ``store`` fixture that
offers the capability — SQLite always, PostgreSQL when ``ONYA_TEST_PG_DSN`` is set; the
filesystem backend is skipped (it is not an ``AssertionStore``).

    pytest -s test/store/test_store_assertions.py
'''

import pytest

from onya.store import AssertionStore
from store_helpers import DOCHEADER, NAME, parse


FRIENDS = DOCHEADER + '''
# A [Person]

* name: Ada
* knows -> B

# B [Person]

* name: Bee
* knows -> C

# C [Person]

* name: Cee
'''

KNOWS = 'https://schema.org/knows'
NAME_P = 'https://schema.org/name'


@pytest.fixture(autouse=True)
def _require_assertion_store(store):
    if not isinstance(store, AssertionStore):
        pytest.skip('backend does not offer the AssertionStore capability')


async def test_match_by_origin(store):
    await store.put(NAME, parse(FRIENDS))
    rows = [(str(o), str(r), str(t)) async for o, r, t, ann in store.match(NAME, 'http://e.o/A')]
    assert (str('http://e.o/A'), NAME_P, 'Ada') in rows
    assert (str('http://e.o/A'), KNOWS, 'http://e.o/B') in rows


async def test_match_by_origin_and_label(store):
    await store.put(NAME, parse(FRIENDS))
    rows = [t async for o, r, t, ann in store.match(NAME, 'http://e.o/A', KNOWS)]
    assert [str(t) for t in rows] == ['http://e.o/B']


async def test_match_unknown_graph_is_empty(store):
    rows = [r async for r in store.match('http://e.o/nope', 'http://e.o/A')]
    assert rows == []


async def test_subgraph_bounded_expansion(store):
    await store.put(NAME, parse(FRIENDS))
    one = await store.subgraph(NAME, {'http://e.o/A'}, hops=1)
    # A fully described; B reached; C only as a dangling bare target of B's edge
    assert 'http://e.o/A' in one.nodes and 'http://e.o/B' in one.nodes
    assert list(one['http://e.o/A'].traverse(KNOWS))
    # A's own name survives; C carries no assertions at 1 hop (dangling)
    assert {p.value for p in one['http://e.o/A'].getprop(NAME_P)} == {'Ada'}
    assert not list(one['http://e.o/C'].getprop(NAME_P))


async def test_add_and_remove_roundtrip(store):
    await store.put(NAME, parse(DOCHEADER + '\n# A [Person]\n\n* name: Ada\n'))
    await store.add(NAME, 'http://e.o/A', 'https://schema.org/age', '40', kind='P')
    got = [str(t) async for o, r, t, ann in store.match(NAME, 'http://e.o/A', 'https://schema.org/age')]
    assert got == ['40']
    await store.remove(NAME, 'http://e.o/A', 'https://schema.org/age', '40', kind='P')
    got2 = [str(t) async for o, r, t, ann in store.match(NAME, 'http://e.o/A', 'https://schema.org/age')]
    assert got2 == []
