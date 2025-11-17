# -*- coding: utf-8 -*-
# test_graphobj.py
'''
Basic graph object tests

pytest -s test/test_graphobj.py
'''

# import functools

# Requires pytest-mock

from amara.iri import I

from onya.graph import node, property_, edge

T = I('http://example.org/')

# @pytest.mark.parametrize('doc', DOC_CASES)
def test_node_1():
    n1 = node(T('spam'), T('Thing'))
    assert n1.id == T('spam')
    assert n1.types == set([T('Thing')])
    assert len(n1.properties) == 0

    p1 = n1.add_property(T('title'), 'Give me a cookie!')
    assert len(n1.properties) == 1

    n1.add_property(T('genre'), 'troublemaker')
    assert len(n1.properties) == 2
    assert isinstance(p1, property_)

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


