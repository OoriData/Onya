# -*- coding: utf-8 -*-
# test_graph.py
'''
Basic graph object tests

pytest -s test/test_graph.py
'''

# import functools

# Requires pytest-mock

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

    g2 = graph(nodes=[n1])
    # Graphs are allowed to share nodes
    assert g1[T('spam')] == g2[T('spam')]

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


