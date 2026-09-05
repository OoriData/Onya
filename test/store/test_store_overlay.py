# -*- coding: utf-8 -*-
# test/store/test_store_overlay.py
'''
Behavioral tests for the ``OverlayReadStore`` capability (read-time union/scoped access
across multiple named graphs, without disturbing per-graph storage; see issue #32). Runs
against every backend from the ``store`` fixture that offers the capability — SQLite
always, PostgreSQL when ``ONYA_TEST_PG_DSN`` is set; the filesystem backend is skipped (it
is not an ``OverlayReadStore`` — see its docstring).

    pytest -s test/store/test_store_overlay.py
'''

import pytest

from onya.graph import GraphMergeError
from onya.store import OverlayReadStore
# from onya.serial.literate import LiterateParser

from store_helpers import canon, put_each, reference


@pytest.fixture(autouse=True)
def _require_overlay_store(store):
    if not isinstance(store, OverlayReadStore):
        pytest.skip('backend does not offer the OverlayReadStore capability')


NAME_P = 'https://schema.org/name'
KNOWS = 'https://schema.org/knows'
AGE = 'https://schema.org/age'

DOC_A = '''\
# @docheader

* @document: http://e.o/docA
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka
* knows -> Ify
'''

DOC_B = '''\
# @docheader

* @document: http://e.o/docB
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* age: 28
'''

DOC_C = '''\
# @docheader

* @document: http://e.o/docC
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* age: 28
'''


# --- union(): basic ------------------------------------------------------------------

async def test_union_of_two_named_graphs_equals_in_memory_union(store):
    names = await put_each(store, DOC_A, DOC_B)
    got = await store.union(names)
    assert canon(got) == canon(reference(DOC_A, DOC_B))


async def test_union_order_independent(store):
    names = await put_each(store, DOC_A, DOC_B)
    forward = await store.union(names)
    backward = await store.union(list(reversed(names)))
    assert canon(forward) == canon(backward)


async def test_union_idempotent_on_repeated_name(store):
    '''Rule 2: unioning a graph with itself (by naming it twice) changes nothing.'''
    names = await put_each(store, DOC_A)
    got = await store.union(names + names)
    assert canon(got) == canon(reference(DOC_A))


async def test_union_three_graphs_nway(store):
    '''N-way grouping beyond pairwise: three graphs, two of which corroborate the same fact.'''
    names = await put_each(store, DOC_A, DOC_B, DOC_C)
    got = await store.union(names)
    assert canon(got) == canon(reference(DOC_A, DOC_B, DOC_C))


# --- union(): error handling ----------------------------------------------------------

async def test_union_empty_names_raises_value_error(store):
    with pytest.raises(ValueError):
        await store.union([])


async def test_union_unknown_name_raises_key_error(store):
    names = await put_each(store, DOC_A)
    with pytest.raises(KeyError):
        await store.union(names + ['http://e.o/does-not-exist'])


async def test_union_rule1_conflict_raises_graph_merge_error(store):
    '''Two named graphs both declaring the same @id with mismatched skeletons -- Rule 1.'''
    doc_x = '''\
# @docheader

* @document: http://e.o/docX
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* knows -> Ify
  * @id: friendship
'''
    doc_y = '''\
# @docheader

* @document: http://e.o/docY
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* knows -> Bee
  * @id: friendship
'''
    names = await put_each(store, doc_x, doc_y)
    with pytest.raises(GraphMergeError):
        await store.union(names)


# --- match_across() --------------------------------------------------------------------

async def test_match_across_returns_rows_from_both_graphs(store):
    names = await put_each(store, DOC_A, DOC_B)
    rows = [(str(o), str(r), str(t)) async for o, r, t, ann in store.match_across(names)]
    assert (str('http://e.o/Chuks'), NAME_P, 'Chukwuemeka') in rows
    assert (str('http://e.o/Chuks'), AGE, '28') in rows


async def test_match_across_merges_corroborating_rows(store):
    '''Two graphs asserting the identical fact merge into ONE match() row, not two.'''
    names = await put_each(store, DOC_B, DOC_C)  # both assert age: 28
    rows = [row async for row in store.match_across(names, label=AGE)]
    assert len(rows) == 1


async def test_match_across_where_predicate(store):
    doc = '''\
# @docheader

* @document: http://e.o/docConf
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Filing [Thing]

* value: "100"
    * confidence: 0.9
* value: "200"
    * confidence: 0.5
'''
    names = await put_each(store, doc)
    high = [row async for row in
           store.match_across(names, label='https://schema.org/value',
                              where=('https://schema.org/confidence', '>', 0.8))]
    assert len(high) == 1
    assert high[0][2] == '100'


# --- subgraph_across() ------------------------------------------------------------------

async def test_subgraph_across_includes_neighborhood_from_both_graphs(store):
    names = await put_each(store, DOC_A, DOC_B)
    sg = await store.subgraph_across(names, {'http://e.o/Chuks'}, hops=1)
    assert 'http://e.o/Chuks' in sg.nodes
    assert 'http://e.o/Ify' in sg.nodes  # reached via DOC_A's top-level `knows` edge
    chuks = sg['http://e.o/Chuks']
    values = {p.label: p.value for p in chuks.properties}
    assert values.get(NAME_P) == 'Chukwuemeka'  # from DOC_A
    assert values.get(AGE) == '28'              # from DOC_B, same node id -> merged
