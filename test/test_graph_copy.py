# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# test/test_graph_copy.py
'''
`graph.copy()` and `graph.subgraph(ids, hops)` (#56).

    pytest -s test/test_graph_copy.py
'''

import io

import pytest

from onya.graph import graph
from onya.serial.literate import read, write
from onya.store import connect

DOC = '''# @docheader
* @document: http://example.org/doc
* @nodebase: http://example.org/kg/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab

# a [Person <ex:Student>]
* name: Ada
  * ex:note: first name
* age: 36
  * @as: number
* knows -> b [=a-knows-b]
  * startDate: "2018"
* about -> a-knows-b

# b [Person]
* name: Bo
* knows -> c

# c [Person]
* name: Cy
* knows -> d

# d [Person]
* name: Di
'''


def canon(g):
    '''Order-free, object-free structure of a graph: what two equal graphs must agree on.'''
    def assertion(a):
        kids = sorted(map(assertion, [*a.properties, *a.edges]), key=repr)
        body = ('P', a.value) if hasattr(a, 'value') else ('E', str(a.target.id))
        return (str(a.label), body, str(a.interp), str(a.id), tuple(kids))
    return {str(nid): (sorted(map(str, n.types)), sorted(map(assertion, [*n.properties, *n.edges]), key=repr))
            for nid, n in g.nodes.items()}


@pytest.fixture
def g():
    return read(DOC).graph


def test_copy_has_the_same_structure(g):
    dup = g.copy()
    assert canon(dup) == canon(g)
    assert dup.prefixes == g.prefixes and dup.prefixes is not g.prefixes
    assert set(dup.assertion_ids) == set(g.assertion_ids) == {'http://example.org/kg/a-knows-b'}
    out = io.StringIO()
    write(g, out)
    dup_out = io.StringIO()
    write(dup, dup_out)
    assert dup_out.getvalue() == out.getvalue()


def test_copy_shares_no_objects(g):
    dup = g.copy()
    for nid, n in g.nodes.items():
        assert dup[nid] is not n
        assert not ({id(p) for p in n.properties} & {id(p) for p in dup[nid].properties})
    assert all(e.target is dup.nodes[e.target.id] for n in dup.nodes.values() for e in n.edges
               if e.target.id in dup.nodes and e.target.id != 'http://example.org/kg/a-knows-b')


def test_edge_to_an_assertion_points_at_the_copy(g):
    dup = g.copy()
    about = next(dup['http://example.org/kg/a'].getedge('about'))
    knows = next(dup['http://example.org/kg/a'].getedge('knows'))
    assert about.target is knows and about.target is not next(g['http://example.org/kg/a'].getedge('knows'))
    assert dup.assertion_ids['http://example.org/kg/a-knows-b'] is knows


def test_mutating_the_copy_leaves_the_original_alone(g):
    before = canon(g)
    dup = g.copy()
    ada = dup['http://example.org/kg/a']
    next(ada.getprop('name')).value = 'Changed'
    ada.add_property('https://schema.org/email', 'a@example.org')
    dup['http://example.org/kg/b'].types.add('https://schema.org/Thing')
    assert canon(g) == before and canon(dup) != before


def test_mutating_the_original_leaves_the_copy_alone(g):
    dup = g.copy()
    before = canon(dup)
    next(g['http://example.org/kg/a'].getprop('name')).value = 'Changed'
    del g['http://example.org/kg/d']
    assert canon(dup) == before


def test_copy_is_a_full_graph(g):
    dup = g.copy()  # CURIE accessors resolve through the copied prefixes; inbound index works
    assert dup['http://example.org/kg/a'].one('name') == 'Ada'
    assert [e.origin.id for e in dup.inbound('http://example.org/kg/c')] == ['http://example.org/kg/b']


def test_copy_survives_union_of_the_original(g):
    '''The motivating case: union consumes its argument, so union a copy and keep the original.'''
    other = read(DOC.replace('# d [Person]\n* name: Di', '# d [Person]\n* name: Dee')).graph
    before = canon(g)
    g.copy().union(other.copy())
    assert canon(g) == before and 'http://example.org/kg/d' in other.nodes
    assert len(other['http://example.org/kg/d'].properties) == 1


def test_copy_of_empty_graph():
    assert len(graph().copy()) == 0


def ids(g):
    return {str(n) for n in g.nodes}


A, B, C, D = (f'http://example.org/kg/{x}' for x in 'abcd')


def test_subgraph_hops(g):
    assert ids(g.subgraph({A}, hops=0)) == {A, B}  # the edge's target stays as a bare node...
    assert not list(g.subgraph({A}, hops=0)[B].getprop('name'))  # ...with no assertions
    one = g.subgraph({A})
    assert ids(one) == {A, B, C} and one[B].one('name') == 'Bo' and not list(one[C].getprop('name'))
    assert ids(g.subgraph({A}, hops=2)) == {A, B, C, D}
    assert g.subgraph({A}, hops=3)[D].one('name') == 'Di'
    assert ids(g.subgraph({D}, hops=5)) == {D}  # nothing outward


def test_subgraph_unknown_roots_ignored(g):
    assert len(g.subgraph({'http://example.org/kg/nope'})) == 0
    assert ids(g.subgraph({'http://example.org/kg/nope', B}, hops=0)) == {B, C}


def test_subgraph_is_a_copy_and_keeps_assertion_ids(g):
    sub = g.subgraph({A}, hops=0)
    assert sub[A] is not g[A]
    knows = next(sub[A].getedge('knows'))
    assert knows.id == 'http://example.org/kg/a-knows-b'
    assert next(sub[A].getedge('about')).target is knows
    assert sub.prefixes == g.prefixes


def test_subgraph_edge_to_assertion_outside_becomes_a_bare_node(g):
    # b's neighborhood excludes `a`, which owns the identified assertion a-knows-b
    g[B].add_edge('https://schema.org/about', g.assertion_ids['http://example.org/kg/a-knows-b'])
    g[B].add_edge('https://schema.org/mentions', g.assertion_ids['http://example.org/kg/a-knows-b'])
    sub = g.subgraph({B}, hops=0)
    targets = {id(e.target) for e in [*sub[B].getedge('about'), *sub[B].getedge('mentions')]}
    assert len(targets) == 1  # one shared bare node, not two
    assert 'http://example.org/kg/a-knows-b' in sub.nodes and not sub.assertion_ids


def flat(n):
    '''A node's own assertions as (label, value-or-target) pairs.'''
    return sorted((str(x.label), getattr(x, 'value', None) or str(x.target.id)) for x in [*n.properties, *n.edges])


CASES = (({A}, 0), ({A}, 1), ({A}, 2), ({B, D}, 1))


async def test_subgraph_agrees_with_the_sqlite_store(tmp_path):
    parsed = read(DOC)
    async with await connect(f'sqlite:{tmp_path}/app.db') as store:
        await store.put(parsed.doc_iri, read(DOC).graph)
        for roots, hops in CASES:
            from_store = await store.subgraph(parsed.doc_iri, roots, hops)
            local = parsed.graph.subgraph(roots, hops)
            assert ids(local) == ids(from_store), (roots, hops)
            assert {n: flat(local[n]) for n in local.nodes} == {n: flat(from_store[n]) for n in local.nodes}


def test_subgraph_agrees_with_the_cross_graph_extractor(g):
    from onya.store._relational import extract_subgraph  # the in-memory path behind subgraph_across
    for roots, hops in CASES:
        theirs = extract_subgraph(g, {str(r) for r in roots}, hops)
        mine = g.subgraph(roots, hops)
        assert ids(mine) == ids(theirs), (roots, hops)
        assert {n: flat(mine[n]) for n in mine.nodes} == {n: flat(theirs[n]) for n in mine.nodes}
