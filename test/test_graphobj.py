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


def test_any_prop_value():
    n = node(T('spam'), T('Thing'))
    assert n.any_prop_value(T('title')) is None            # no match -> default
    assert n.any_prop_value(T('title'), 'fallback') == 'fallback'

    n.add_property(T('title'), 'Give me a cookie!')
    assert n.any_prop_value(T('title')) == 'Give me a cookie!'  # raw value, not the object

    # more than one match: arbitrary pick, but always one of the actual values (never None/default)
    n.add_property(T('title'), 'Or a muffin!')
    assert n.any_prop_value(T('title')) in {'Give me a cookie!', 'Or a muffin!'}


def test_any_edge_target():
    n1 = node(T('spam'), T('Thing'))
    assert n1.any_edge_target(T('maker')) is None
    assert n1.any_edge_target(T('maker'), 'fallback') == 'fallback'

    n2 = node(T('Homer'), T('Agent'))
    n1.add_edge(T('maker'), n2)
    assert n1.any_edge_target(T('maker')) is n2                 # raw target, not the edge object


#def test_node_2():
#    og = graph()


