# -*- coding: utf-8 -*-
# test_graph.py
'''
Basic graph object tests

pytest -s test/test_graph.py
'''

# import functools

# Requires pytest-mock

import pytest
from amara.iri import I

from onya.graph import node, graph, property_, edge

T = I('http://example.org')

# @pytest.mark.parametrize('doc', DOC_CASES)
def test_graph_1():
    g1 = graph()

    n1 = g1.node(T('spam'), T('Thing'))
    assert n1.id == T('spam')
    assert n1.types == set([T('Thing')])
    assert len(n1.properties) == 0

    p1 = n1.add_property(T('title'), 'Give me a cookie!')
    assert len(n1.properties) == 1

    n1.add_property(T('genre'), 'troublemaker')
    assert len(n1.properties) == 2
    assert isinstance(p1, property_)

    # Graphs may still share a node object, but it's flagged: the node's (weak) back-reference
    # follows the latest graph, so only that graph's indexes track mutations made through it.
    with pytest.warns(UserWarning, match='already in another live graph'):
        g2 = graph(nodes=[n1])
    assert g1[T('spam')] == g2[T('spam')]
    assert n1._graph is g2

    n2 = node(T('Homer'), T('Agent'))
    e1 = n1.add_edge(T('maker'), n2)
    assert len(n1.properties) == 2
    assert len(n1.edges) == 1
    assert isinstance(e1, edge)
    assert e1.target == n2
    assert list(n1.traverse(T('maker'))) == [e1]
    # Should be syllogistic from above 2 asserts, but good to exercise different idioms
    assert [ e.target for e in n1.traverse(T('maker')) ] == [n2]


#def test_node_2():
#    og = graph()


