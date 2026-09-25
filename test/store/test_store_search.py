# -*- coding: utf-8 -*-
# test/store/test_store_search.py
'''
``SearchStore`` conformance: every backend's ``search`` agrees with the in-memory
``onya.query.search`` — exactly on file/SQLite; on PostgreSQL (whose fuzzy scores are
``pg_trgm``-based) in what ``SearchStore`` guarantees: identical non-fuzzy hits, the same top
hit, and the same tier for any node both return. Plus ``nodes_by_type`` and the sync facade.

    pytest -s test/store/test_store_search.py
'''

import pytest
from amara.iri import I

from onya.serial import literate
from onya.store import SearchStore
from onya.store.sync import SyncStore

NAME = I('http://example.org/graphs/people')
P = 'http://example.org/people/'
SCHEMA = I('https://schema.org/')

DOC = '''# @docheader
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# ada [Person]
* name: Ada Lovelace
* alternateName: Augusta Ada King
* worksFor -> analytical-engine-co
    * note: ada lovelace nested, never searched

# adah [Person]
* name: Adah Isaacs Menken

# babbage [Person]
* name: Charles Babbage
* birthDate: 1791
    * @as: number

# analytical-engine-co [Organization]
* name: Analytical Engine Company
'''

CASES = [
    ('ada lovelac', dict(labels=[SCHEMA('name'), SCHEMA('alternateName')])),
    ('ada', dict(labels=[SCHEMA('name')])),
    ('king', dict(labels=[SCHEMA('name'), SCHEMA('alternateName')], types=[SCHEMA('Person')])),
    ('ada', dict()),
    ('ada', dict(per_node=False)),
    ('ada', dict(limit=1)),
    ('1791', dict()),
    ('analytical engine company', dict(types=[SCHEMA('Organization')])),
    ('zzzz', dict()),
]


def _shape(hits, exact: bool):
    if exact:
        return [(str(h.node_id), str(h.label), h.value, h.tier, round(h.score, 6)) for h in hits]
    return [(str(h.node_id), str(h.label), h.value, h.tier) for h in hits]


@pytest.mark.parametrize('query,kwargs', CASES)
async def test_search_matches_in_memory(store, backend, query, kwargs):
    assert isinstance(store, SearchStore)
    await store.put(NAME, literate.read(DOC).graph)
    expected = literate.read(DOC).graph.search(query, **kwargs)
    got = await store.search(NAME, query, **kwargs)
    assert all(h.node is None and h.assertion is None for h in got)
    if backend != 'postgres':
        assert _shape(got, True) == _shape(expected, True)
        return
    # PostgreSQL: trigram scores decide fuzzy inclusion/order, so compare the guaranteed part.
    def strong(hits):
        return sorted(s for s in _shape(hits, False) if s[3] != 'fuzzy')
    assert strong(got) == strong(expected)
    if expected and got:
        assert _shape(got, False)[0] == _shape(expected, False)[0]
    tier_of = {(s[0], s[1], s[2]): s[3] for s in _shape(expected, False)}
    for s in _shape(got, False):
        assert tier_of.get((s[0], s[1], s[2]), s[3]) == s[3]


async def test_search_absent_graph_is_empty(store):
    assert await store.search(I('http://example.org/graphs/nope'), 'ada') == []


async def test_nodes_by_type(store):
    await store.put(NAME, literate.read(DOC).graph)
    people = [str(n) async for n in store.nodes_by_type(NAME, SCHEMA('Person'))]
    assert sorted(people) == [P + 'ada', P + 'adah', P + 'babbage']
    assert [n async for n in store.nodes_by_type(NAME, SCHEMA('Place'))] == []


async def test_custom_normalize(store):
    await store.put(NAME, literate.read(DOC).graph)

    def consonants(s):
        return ''.join(c for c in s.casefold() if c.isalpha() and c not in 'aeiou')
    hits = await store.search(NAME, 'Chorlos Bebbege', labels=[SCHEMA('name')], normalize=consonants)
    assert hits[0].tier == 'exact' and hits[0].node_id == P + 'babbage'


@pytest.mark.parametrize('query', ['ada lovelac', 'ada', 'babage', 'engine co'])
async def test_rapidfuzz_similarity_matches_in_memory(store, query):
    '''An explicit similarity runs in-process on every backend (PostgreSQL included), so exact.'''
    pytest.importorskip('rapidfuzz')
    await store.put(NAME, literate.read(DOC).graph)
    expected = literate.read(DOC).graph.search(query, similarity='rapidfuzz')
    got = await store.search(NAME, query, similarity='rapidfuzz')
    assert _shape(got, True) == _shape(expected, True)


def test_sync_facade_search(tmp_path):
    from onya.store.sync import connect
    with connect(f'sqlite:{tmp_path}/s.db') as st:
        assert isinstance(st, SyncStore) and isinstance(st, SearchStore)
        st.put(NAME, literate.read(DOC).graph)
        hits = st.search(NAME, 'ada lovelac', labels=[SCHEMA('name')], types=[SCHEMA('Person')], limit=5)
        assert hits[0].node_id == P + 'ada'
        assert sorted(map(str, st.nodes_by_type(NAME, SCHEMA('Organization')))) == [P + 'analytical-engine-co']
