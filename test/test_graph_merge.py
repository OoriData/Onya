# -*- coding: utf-8 -*-
# test_graph_merge.py
'''
Tests for graph merge — collapsing duplicate assertions into a single occurrence
under the SPEC identity rules (SPEC.md § Identity and graph merge).

Merge is an **explicit, on-demand** operation: `graph.merge()`. Parsing never merges —
parsing several overlapping documents into one graph accumulates their assertions as
distinct occurrences, which collapse only when a consumer calls `merge()`.

    pytest -s test/test_graph_merge.py
'''

import pytest

from amara.iri import I

from onya.graph import graph, GraphMergeError
from onya.serial.literate import LiterateParser


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''


def _parse(*docs):
    '''Parse one or more Onya Literate strings into a single graph (no merge).'''
    g = graph()
    for d in docs:
        LiterateParser().parse(d, g)
    return g


def _merged(*docs):
    '''Parse then explicitly merge — the deliberate, on-demand union.'''
    g = _parse(*docs)
    g.merge()
    return g


def _props(n, label):
    return list(n.getprop(label))


def _edges(n, label):
    return list(n.traverse(label))


# --- parsing does not merge ---------------------------------------------------------

def test_parse_alone_does_not_merge():
    '''Duplicates accumulate on parse; they collapse only on an explicit merge().'''
    doc = DOCHEADER + '''
# Chuks [Person]

* age: 28
'''
    g = _parse(doc, doc)  # parsed twice, not merged
    assert len(_props(g['http://e.o/Chuks'], 'https://schema.org/age')) == 2
    g.merge()
    assert len(_props(g['http://e.o/Chuks'], 'https://schema.org/age')) == 1


def test_parse_merge_flag_is_convenience():
    '''parse(..., merge=True) runs merge() once after parsing — a one-call shorthand.'''
    doc = DOCHEADER + '''
# Chuks [Person]

* age: 28
'''
    g = graph()
    LiterateParser().parse(doc, g)                 # first pass: accumulates
    LiterateParser().parse(doc, g, merge=True)     # second pass + merge in one call
    assert len(_props(g['http://e.o/Chuks'], 'https://schema.org/age')) == 1


# --- Rule 2: anonymous assertions with equal skeletons merge -------------------------

def test_identical_property_merges():
    '''Two identical property lines collapse to a single assertion under merge.'''
    g = _merged(DOCHEADER + '''
# Chuks [Person]

* age: 28
* age: 28
''')
    assert len(_props(g['http://e.o/Chuks'], 'https://schema.org/age')) == 1


def test_distinct_values_stay_distinct():
    '''Same label, different value: two genuine claims, both retained through merge.'''
    g = _merged(DOCHEADER + '''
# Chuks [Person]

* nickname: Chuk
* nickname: CK
''')
    vals = {p.value for p in _props(g['http://e.o/Chuks'], 'https://schema.org/nickname')}
    assert vals == {'Chuk', 'CK'}


def test_merged_edges_union_their_nested_assertions():
    '''Two extractions of the same edge merge; their nested assertions are unioned.'''
    g = _merged(
        DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * since: 2018
''',
        DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * strength: close
''',
    )
    knows = _edges(g['http://e.o/Chuks'], 'https://schema.org/knows')
    assert len(knows) == 1
    nested = {str(p.label) for p in knows[0].properties}
    assert nested == {'https://schema.org/since', 'https://schema.org/strength'}


def test_nested_duplicate_merges_recursively():
    '''Merge is recursive: duplicate nested assertions under a merged parent collapse.'''
    doc = DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * since: 2018
'''
    g = _merged(doc, doc)
    knows = _edges(g['http://e.o/Chuks'], 'https://schema.org/knows')
    assert len(knows) == 1
    assert len(list(knows[0].getprop('https://schema.org/since'))) == 1


def test_edges_to_different_targets_stay_distinct():
    '''An edge's target is part of its skeleton: different targets do not merge.'''
    g = _merged(DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
* knows -> Ada
''')
    assert len(_edges(g['http://e.o/Chuks'], 'https://schema.org/knows')) == 2


# --- Rule 3: an identified assertion never merges with an anonymous one --------------

def test_identified_and_anonymous_stay_distinct():
    '''Equal skeletons, but one carries an @id: they remain two distinct assertions.'''
    g = _merged(DOCHEADER + '''
# Chuks [Person]

* age: 28
* age: 28
  * @id: the-canonical-age
''')
    props = _props(g['http://e.o/Chuks'], 'https://schema.org/age')
    assert len(props) == 2
    assert sum(1 for p in props if p.id is not None) == 1


# --- Rule 1: same-id assertions are the same assertion (direct model + graph.merge) --

def test_same_id_equal_skeleton_merges():
    '''Two same-id assertions with matching skeletons merge, unioning nested assertions.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p1 = n.add_property(I('http://s/age'), '28')
    p1.id = I('http://e.o/a1')
    p1.add_property(I('http://s/note'), 'from-A')
    p2 = n.add_property(I('http://s/age'), '28')
    p2.id = I('http://e.o/a1')
    p2.add_property(I('http://s/note'), 'from-B')

    g.merge()
    survivors = _props(n, I('http://s/age'))
    assert len(survivors) == 1
    notes = {p.value for p in survivors[0].getprop(I('http://s/note'))}
    assert notes == {'from-A', 'from-B'}


def test_same_id_mismatched_skeleton_is_merge_error():
    '''Same id but differing (label, value) is a merge error, per Rule 1.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p1 = n.add_property(I('http://s/age'), '28')
    p1.id = I('http://e.o/a1')
    p2 = n.add_property(I('http://s/age'), '29')  # differing value => skeleton mismatch
    p2.id = I('http://e.o/a1')

    with pytest.raises(GraphMergeError, match='skeleton'):
        g.merge()


def test_merge_is_idempotent_operation():
    '''Running merge twice changes nothing after the first pass.'''
    g = _merged(DOCHEADER + '''
# Chuks [Person]

* age: 28
* age: 28
''')
    before = len(_props(g['http://e.o/Chuks'], 'https://schema.org/age'))
    g.merge()
    after = len(_props(g['http://e.o/Chuks'], 'https://schema.org/age'))
    assert before == after == 1
