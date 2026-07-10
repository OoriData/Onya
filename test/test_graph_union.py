# -*- coding: utf-8 -*-
# test_graph_union.py
'''
Tests for model-level graph union — folding one graph into another and normalizing under
the SPEC identity rules (SPEC.md § Identity and graph merge) plus the interp amendment.

`graph.union(other)` is the operation every store backend's `put(merge=True)` is defined
against: it must be observationally identical to parsing both sources into one graph and
calling `merge()`.

    pytest -s test/test_graph_union.py
'''

import pytest

from amara.iri import I

from onya.graph import graph, GraphMergeError, AssertionIdConflict
from onya.serial.literate import LiterateParser


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''


def _g(*docs):
    '''Parse the given docs into a fresh graph (no merge).'''
    g = graph()
    for d in docs:
        LiterateParser().parse(d, g)
    return g


def _merged_into_one(*docs):
    '''Parse all docs into one graph and merge() — the reference the union must match.'''
    g = _g(*docs)
    g.merge()
    return g


def _props(n, label):
    return list(n.getprop(label))


def _edges(n, label):
    return list(n.traverse(label))


CHUKS = 'http://e.o/Chuks'
AGE = 'https://schema.org/age'
KNOWS = 'https://schema.org/knows'


# --- union == parse-both-then-merge --------------------------------------------------

def test_union_matches_single_graph_merge():
    doc_a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    doc_b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    ref = _merged_into_one(doc_a, doc_b)

    g = _g(doc_a).union(_g(doc_b))
    assert len(_props(g[CHUKS], AGE)) == len(_props(ref[CHUKS], AGE)) == 1


def test_union_is_idempotent():
    doc = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    g = _g(doc)
    g.union(_g(doc))
    g.union(_g(doc))
    assert len(_props(g[CHUKS], AGE)) == 1


def test_union_adopts_disjoint_nodes():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Ada [Person]\n\n* age: 31\n'
    g = _g(a).union(_g(b))
    assert CHUKS in g and 'http://e.o/Ada' in g


def test_union_unions_nested_assertions():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* knows -> Ify\n  * since: 2018\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* knows -> Ify\n  * strength: close\n'
    g = _g(a).union(_g(b))
    knows = _edges(g[CHUKS], KNOWS)
    assert len(knows) == 1
    nested = {str(p.label) for p in knows[0].properties}
    assert nested == {'https://schema.org/since', 'https://schema.org/strength'}


def test_union_rebinds_edge_targets_to_canonical_nodes():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* knows -> Ify\n'
    b = DOCHEADER + '\n# Ify [Person]\n\n* age: 30\n'
    g = _g(a).union(_g(b))
    knows = _edges(g[CHUKS], KNOWS)
    assert knows[0].target is g['http://e.o/Ify']


# --- Rule 1: identified assertions ---------------------------------------------------

def test_union_same_id_merges():
    g = graph()
    n = g.node(I('http://e.o/N'))
    p = n.add_property(I('http://s/age'), '28')
    g.register_assertion_id(I('http://e.o/a1'), p)
    p.add_property(I('http://s/note'), 'from-A')

    other = graph()
    n2 = other.node(I('http://e.o/N'))
    p2 = n2.add_property(I('http://s/age'), '28')
    other.register_assertion_id(I('http://e.o/a1'), p2)
    p2.add_property(I('http://s/note'), 'from-B')

    g.union(other)
    survivors = _props(g[I('http://e.o/N')], I('http://s/age'))
    assert len(survivors) == 1
    notes = {p.value for p in survivors[0].getprop(I('http://s/note'))}
    assert notes == {'from-A', 'from-B'}
    assert g.assertion_ids[I('http://e.o/a1')] is survivors[0]


def test_union_same_id_mismatched_skeleton_errors():
    g = graph()
    n = g.node(I('http://e.o/N'))
    p = n.add_property(I('http://s/age'), '28')
    g.register_assertion_id(I('http://e.o/a1'), p)

    other = graph()
    n2 = other.node(I('http://e.o/N'))
    p2 = n2.add_property(I('http://s/age'), '29')
    other.register_assertion_id(I('http://e.o/a1'), p2)

    with pytest.raises(GraphMergeError, match='skeleton'):
        g.union(other)


# --- Rule 3 + interp amendment -------------------------------------------------------

def test_union_identified_and_anonymous_stay_distinct():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: canonical-age\n'
    g = _g(a).union(_g(b))
    props = _props(g[CHUKS], AGE)
    assert len(props) == 2
    assert sum(1 for p in props if p.id is not None) == 1


def test_union_one_sided_interp_adoption():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    g = _g(a).union(_g(b))
    props = _props(g[CHUKS], AGE)
    assert len(props) == 1
    assert str(props[0].interp) == 'http://purl.org/onya/vocab/interp/number'


def test_union_conflicting_interps_stay_distinct():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: text\n'
    g = _g(a).union(_g(b))
    props = _props(g[CHUKS], AGE)
    assert len(props) == 2
    assert {str(p.interp) for p in props} == {
        'http://purl.org/onya/vocab/interp/number',
        'http://purl.org/onya/vocab/interp/text',
    }


def test_union_null_adopts_nothing_under_ambiguity():
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: text\n'
    c = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'  # contract-free, ambiguous
    g = _g(a).union(_g(b)).union(_g(c))
    props = _props(g[CHUKS], AGE)
    # The NULL row adds nothing and adopts nothing: only the two contract rows survive.
    assert len(props) == 2
    assert all(p.interp is not None for p in props)


# --- id-space collision --------------------------------------------------------------

def test_union_id_space_collision_raises():
    g = graph()
    g.node(I('http://e.o/X'))

    other = graph()
    n = other.node(I('http://e.o/N'))
    p = n.add_property(I('http://s/age'), '28')
    other.register_assertion_id(I('http://e.o/X'), p)  # collides with node id X

    with pytest.raises(AssertionIdConflict):
        g.union(other)
