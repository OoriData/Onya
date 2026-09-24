# -*- coding: utf-8 -*-
# test/test_graph_inbound.py
'''
`graph.inbound()` — reverse-edge lookup backed by a lazily rebuilt index — and
`node.reverse()` as a thin wrapper over it.

    pytest -s test/test_graph_inbound.py
'''

from amara.iri import I

from onya.graph import graph
from onya.serial import literate

P = 'http://example.org/people/'
S = 'https://schema.org/'

DOC = '''# @docheader
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# ada [Person]
* worksFor -> aec
* knows -> babbage
    * introducedBy -> somerville

# babbage [Person]
* worksFor -> aec

# aec [Organization]
'''


def origins(edges):
    return sorted(str(e.origin.id).removeprefix(P) for e in edges)


def test_inbound_by_label_and_id():
    g = literate.read(DOC).graph
    assert origins(g.inbound(P + 'aec', label='schema:worksFor')) == ['ada', 'babbage']
    assert origins(g.inbound(g[P + 'aec'], label=I(S + 'worksFor'))) == ['ada', 'babbage']
    assert origins(g.inbound(P + 'aec', label='knows')) == []
    assert list(g.inbound(P + 'nobody')) == []


def test_inbound_includes_nested_edges():
    g = literate.read(DOC).graph
    [e] = g.inbound(P + 'somerville')
    assert e.label == S + 'introducedBy'
    assert e.origin.label == S + 'knows'  # origin is the `knows` edge, not a node


def test_index_tracks_mutation():
    g = literate.read(DOC).graph
    worksfor = I(S + 'worksFor')
    assert len(list(g.inbound(P + 'aec', worksfor))) == 2   # builds the index
    newbie = g.node(I(P + 'lovelace2'))
    e = newbie.add_edge(worksfor, g[P + 'aec'])
    assert len(list(g.inbound(P + 'aec', worksfor))) == 3
    newbie.remove_edge(e)
    assert len(list(g.inbound(P + 'aec', worksfor))) == 2


def test_index_tracks_union():
    g = literate.read(DOC).graph
    list(g.inbound(P + 'aec'))
    other = literate.read(DOC.replace('# babbage [Person]', '# menabrea [Person]')).graph
    g.union(other)
    assert origins(g.inbound(P + 'aec', 'schema:worksFor')) == ['ada', 'babbage', 'menabrea']


def test_touch_after_direct_edit():
    g = graph()
    a, b, c = g.node(I('a')), g.node(I('b')), g.node(I('c'))
    e = a.add_edge(I('rel'), b)
    assert origins(g.inbound('b')) == ['a']
    e.target = c  # bypasses the API ...
    g.touch()     # ... so invalidate explicitly
    assert origins(g.inbound('c')) == ['a'] and list(g.inbound('b')) == []


def test_index_is_per_graph():
    g, other = literate.read(DOC).graph, literate.read(DOC).graph
    list(g.inbound(P + 'aec'))
    built = g._inbound_index
    other[P + 'ada'].add_edge(I(S + 'worksFor'), other[P + 'aec'])  # mutate a *different* graph
    list(g.inbound(P + 'aec'))
    assert g._inbound_index is built  # not rebuilt


def test_nested_mutation_invalidates_owner():
    g = literate.read(DOC).graph
    assert list(g.inbound(P + 'newcomer')) == []
    [knows] = g[P + 'ada'].getedge('knows')
    knows.add_edge(I(S + 'introducedBy'), g.node(I(P + 'newcomer')))
    assert [e.origin for e in g.inbound(P + 'newcomer')] == [knows]


def test_sharing_a_node_warns_and_rebinds():
    import pytest
    g1, g2 = graph(), graph()
    n = g1.node(I('a'))
    with pytest.warns(UserWarning, match='already in another live graph'):
        g2[I('a')] = n
    assert n._graph is g2
    b = g2.node(I('b'))
    n.add_edge(I('rel'), b)
    assert origins(g2.inbound('b')) == ['a']  # g2 now tracks mutations through n


def test_no_warning_for_move_union_or_dead_graph():
    import gc
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        g1 = graph()
        n = g1.node(I('a'))
        g1[I('a')] = n                 # re-adding to the same graph
        moved = graph()
        del g1[I('a')]
        moved[I('a')] = n              # removed from g1 first: a move, not sharing
        src = literate.read(DOC).graph
        dst = graph()
        dst.union(src)                 # union's explicit handoff
        orphan = literate.read(DOC).graph[P + 'ada']
        gc.collect()
        graph()[orphan.id] = orphan    # previous graph already collected


def test_reverse_is_thin_wrapper():
    g = literate.read(DOC).graph
    assert origins(g[P + 'aec'].reverse(I(S + 'worksFor'), g)) == ['ada', 'babbage']
