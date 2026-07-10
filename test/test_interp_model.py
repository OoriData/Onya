# -*- coding: utf-8 -*-
# test_interp_model.py
'''
Tests for the interpretation model surface (`assertion.interp`) and its interaction with
graph merge. Interpretations are a recorded contract about how a string value is read;
the model stores the IRI as data and never applies it (see SPEC: Data contract layers).

    pytest -s test/test_interp_model.py
'''

import pytest

from amara.iri import I

from onya.graph import graph, GraphMergeError
from onya.terms import ONYA_INTERP


AGE = I('https://schema.org/age')
NUMBER = ONYA_INTERP('number')
DATETIME = ONYA_INTERP('datetime')


def _props(n, label):
    return list(n.getprop(label))


# --- slot basics --------------------------------------------------------------------

def test_interp_defaults_none():
    '''A freshly added property carries no interpretation.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p = n.add_property(AGE, '28')
    assert p.interp is None


def test_add_property_sets_interp():
    '''The optional keyword records the contract in one call.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p = n.add_property(AGE, '28', interp=NUMBER)
    assert p.interp == NUMBER
    assert p.value == '28'  # the value is untouched — always a string


def test_interp_excluded_from_skeleton():
    '''Attaching a contract never changes identity: skeletons match with or without interp.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    bare = n.add_property(AGE, '28')
    typed = n.add_property(AGE, '28', interp=NUMBER)
    assert bare._skeleton == typed._skeleton


# --- merge compatibility (SPEC merge amendment) -------------------------------------

def test_merge_one_sided_adopts():
    '''One assertion has an interp, the other does not: they merge and adopt the interp.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    n.add_property(AGE, '28', interp=NUMBER)
    n.add_property(AGE, '28')  # anonymous, no interp

    g.merge()
    survivors = _props(n, AGE)
    assert len(survivors) == 1
    assert survivors[0].interp == NUMBER


def test_merge_equal_interps_merge():
    '''Same interp on both: a single merged assertion keeping that interp.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    n.add_property(AGE, '28', interp=NUMBER)
    n.add_property(AGE, '28', interp=NUMBER)

    g.merge()
    survivors = _props(n, AGE)
    assert len(survivors) == 1
    assert survivors[0].interp == NUMBER


def test_merge_conflicting_interps_stay_distinct():
    '''Different contracts on the same words are different claims: no merge, no error.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    n.add_property(AGE, '28', interp=NUMBER)
    n.add_property(AGE, '28', interp=DATETIME)

    g.merge()  # not an error
    survivors = _props(n, AGE)
    assert len(survivors) == 2
    assert {p.interp for p in survivors} == {NUMBER, DATETIME}


def test_same_id_conflicting_interps_is_merge_error():
    '''Same explicit id but differing non-absent interps: a merge error (like skeleton mismatch).'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p1 = n.add_property(AGE, '28', interp=NUMBER)
    p1.id = I('http://e.o/a1')
    p2 = n.add_property(AGE, '28', interp=DATETIME)
    p2.id = I('http://e.o/a1')

    with pytest.raises(GraphMergeError, match='interpretation'):
        g.merge()


def test_interp_free_row_drops_against_a_standing_conflict():
    '''An interp-free row that matches two already-conflicting contracts merges into neither.

    Ratified ruling: with X and Y already distinct on the same skeleton, a contract-free
    claim cannot pick a side, its skeleton is already represented, so it adds nothing — no
    third row, and it does not silently attach (with its nested assertions) to X or Y.
    '''
    g = graph()
    n = g.node(I('http://e.o/N'))
    n.add_property(AGE, '1999', interp=NUMBER)
    n.add_property(AGE, '1999', interp=DATETIME)
    bare = n.add_property(AGE, '1999')            # interp-free duplicate of the conflicted skeleton
    bare.add_property(I('https://schema.org/prov'), 'from-bare')

    g.merge()
    survivors = _props(n, AGE)
    assert len(survivors) == 2
    assert {p.interp for p in survivors} == {NUMBER, DATETIME}
    # The dropped NULL's nested prov attached to neither contract row (no arbitrary winner).
    assert all(list(p.getprop('https://schema.org/prov')) == [] for p in survivors)


def test_same_id_one_absent_interp_adopts():
    '''Same id, one interp absent: merge succeeds and adopts the present interp.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    p1 = n.add_property(AGE, '28', interp=NUMBER)
    p1.id = I('http://e.o/a1')
    p2 = n.add_property(AGE, '28')
    p2.id = I('http://e.o/a1')

    g.merge()
    survivors = _props(n, AGE)
    assert len(survivors) == 1
    assert survivors[0].interp == NUMBER
