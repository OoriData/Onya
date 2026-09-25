# -*- coding: utf-8 -*-
# test/store/test_store_prefixes.py
'''
Every backend persists a graph's (non-canonical) prefix map: ``put`` folds by the
``graph.add_prefixes`` rule, ``put(merge=False)`` replaces, reads return it, and multi-graph
reads fold in ``names`` order.

    pytest -s test/store/test_store_prefixes.py
'''

import warnings

import pytest
from amara.iri import I

from onya import view
from onya.graph import graph
from onya.serial import literate
from onya.store import AssertionStore, OverlayReadStore

A = I('http://example.org/graphs/a')
B = I('http://example.org/graphs/b')
P = 'http://example.org/lib/'


def doc(ex_ns='http://example.org/vocab/', extra=''):
    return f'''# @docheader
* @nodebase: http://example.org/lib/
* @schema: https://schema.org/
* @iri:
    * ex: {ex_ns}
{extra}
# ada [Person]
* name: Ada Lovelace
* ex:code: AL
* worksFor -> aec

# aec [Organization]
* name: Analytical Engine Company
'''


def ns(prefixes):
    return {k: v.rstrip('/') for k, v in prefixes.items()}


async def test_roundtrip(store):
    await store.put(A, literate.read(doc()).graph)
    g = await store.get(A)
    assert ns(g.prefixes) == {'schema': 'https://schema.org', 'ex': 'http://example.org/vocab'}
    assert g[P + 'ada'].any_prop_value('ex:code') == 'AL'   # CURIEs work on what get() returns


async def test_merge_adds_and_stored_binding_wins(store):
    await store.put(A, literate.read(doc()).graph)
    incoming = literate.read(doc(ex_ns='http://other.org/', extra='    * foaf: http://xmlns.com/foaf/0.1/\n')).graph
    with pytest.warns(UserWarning, match="Prefix 'ex' clash"):
        await store.put(A, incoming)
    g = await store.get(A)
    assert ns(g.prefixes)['ex'] == 'http://example.org/vocab'       # stored wins
    assert ns(g.prefixes)['foaf'] == 'http://xmlns.com/foaf/0.1'    # new one added


async def test_same_namespace_new_prefix_is_quiet(store):
    await store.put(A, literate.read(doc()).graph)
    g2 = literate.read(doc()).graph
    g2.prefixes['exv'] = g2.prefixes['ex']
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        await store.put(A, g2)
    assert 'exv' in (await store.get(A)).prefixes


async def test_replace_replaces(store):
    await store.put(A, literate.read(doc()).graph)
    g2 = literate.read(doc(ex_ns='http://other.org/')).graph
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        await store.put(A, g2, merge=False)
    assert ns((await store.get(A)).prefixes)['ex'] == 'http://other.org'


async def test_subgraph_and_across_reads(store):
    if not isinstance(store, AssertionStore):
        pytest.skip('filesystem backend has no subgraph()')
    await store.put(A, literate.read(doc()).graph)
    sub = await store.subgraph(A, {P + 'ada'}, hops=0)
    assert ns(sub.prefixes)['ex'] == 'http://example.org/vocab'
    if not isinstance(store, OverlayReadStore):
        return
    await store.put(B, literate.read(doc(ex_ns='http://other.org/')).graph)
    for read in (lambda: store.union([A, B]), lambda: store.subgraph_across([A, B], {P + 'ada'}),
                 lambda: store.overlay([A, B])):
        with pytest.warns(UserWarning, match="Prefix 'ex' clash"):
            result = await read()
        g = result[0] if isinstance(result, tuple) else result
        assert ns(g.prefixes)['ex'] == 'http://example.org/vocab'   # first-named graph wins


async def test_project_from_store_uses_stored_prefixes(store):
    await store.put(A, literate.read(doc()).graph)
    spec = {'type': 'Person', 'fields': ['name', 'ex:code'], 'follow': [{'edge': 'worksFor', 'show': ['name']}]}
    got = await view.project_from_store(store, A, P + 'ada', spec)   # no prefixes= needed
    assert got == view.project(literate.read(doc()).graph, P + 'ada', spec)


async def test_graph_without_prefixes_stores_none(store):
    g = graph()
    g.node(I(P + 'x')).add_property(I('https://schema.org/name'), 'X')
    await store.put(A, g)
    assert (await store.get(A)).prefixes == {}


async def test_existing_sqlite_store_upgrades_on_open(tmp_path):
    '''A store created before the prefix table existed gains it on open; no version bump.'''
    import sqlite3
    from onya.store import connect
    url, path = f'sqlite:{tmp_path}/old.db', tmp_path / 'old.db'
    async with await connect(url) as st:
        await st.put(A, literate.read(doc()).graph)
    conn = sqlite3.connect(path)
    conn.execute('DROP TABLE onya_graph_prefix')       # simulate a pre-upgrade store
    conn.commit()
    conn.close()
    async with await connect(url) as st:
        assert (await st.get(A)).prefixes == {}         # old data: no prefixes recorded
        await st.put(A, literate.read(doc()).graph)
        assert 'ex' in (await st.get(A)).prefixes
