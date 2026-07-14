# -*- coding: utf-8 -*-
# test_graph_select.py
'''
Tests for graph.select() — the uniform single-pattern selector (the naive-query floor,
cf. 4RDF's complete()), and for graph.match() reimplemented as its tuple projection.

select() yields live assertion objects with a wildcard on every component
(origin/label/value/target/id) plus an optional deep descent into nested assertions.

    pytest -s test/test_graph_select.py
'''

from amara.iri import I

from onya.graph import graph, edge, property_
from onya.serial.literate import LiterateParser


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''

DOC = DOCHEADER + '''
# Chuks [Person]

* name: Chuks
* name: Charles
* age: 40
* knows -> Ify
  * @id: chuks-ify
  * since: 2018
* knows -> Nkiru

# ReviewNote

* disputes -> chuks-ify
'''

CHUKS = I('http://e.o/Chuks')
IFY = I('http://e.o/Ify')
CHUKS_IFY = I('http://e.o/chuks-ify')
NAME = I('https://schema.org/name')
AGE = I('https://schema.org/age')
KNOWS = I('https://schema.org/knows')
SINCE = I('https://schema.org/since')
DISPUTES = I('https://schema.org/disputes')


def _g():
    g = graph()
    LiterateParser().parse(DOC, g)
    return g


# --- component wildcards -------------------------------------------------------------

def test_select_all_wildcard():
    '''No constraints -> every first-level assertion in the graph (6: 5 on Chuks, 1 on ReviewNote).'''
    g = _g()
    assert len(list(g.select())) == 6


def test_select_by_origin_id():
    '''origin as a node id restricts to that node's first-level assertions.'''
    g = _g()
    got = list(g.select(origin=CHUKS))
    assert len(got) == 5
    assert all(a.origin is g[CHUKS] for a in got)


def test_select_by_label_across_graph():
    '''label alone scans the whole graph (the "more selective complete()" case).'''
    g = _g()
    assert len(list(g.select(label=KNOWS))) == 2  # both Chuks->Ify and Chuks->Nkiru
    assert len(list(g.select(label=NAME))) == 2   # multi-valued property, two occurrences


def test_select_value_restricts_to_properties():
    '''value= is the property face of the object slot; edges never match it.'''
    g = _g()
    got = list(g.select(value='Chuks'))
    assert len(got) == 1 and isinstance(got[0], property_) and got[0].label == NAME
    assert list(g.select(label=NAME, value='Charles'))[0].value == 'Charles'


def test_select_target_restricts_to_edges():
    '''target= is the edge face; a target id matches a node target or an identified-assertion target.'''
    g = _g()
    to_ify = list(g.select(target=IFY))
    assert len(to_ify) == 1 and isinstance(to_ify[0], edge) and to_ify[0].label == KNOWS
    # The disputes edge points at the *identified assertion* chuks-ify, matched by its @id.
    to_assertion = list(g.select(target=CHUKS_IFY))
    assert len(to_assertion) == 1 and to_assertion[0].label == DISPUTES


def test_select_value_and_target_conflict():
    '''The two object faces are mutually exclusive.'''
    g = _g()
    try:
        list(g.select(value='Chuks', target=IFY))
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_select_by_id_closes_ticket_4():
    '''Selecting by assertion @id — the gap ticket #4 named — is a first-class mode.'''
    g = _g()
    got = list(g.select(id=CHUKS_IFY))
    assert len(got) == 1
    a = got[0]
    assert isinstance(a, edge) and a.id == CHUKS_IFY and a.label == KNOWS
    assert a is g.assertion_ids[CHUKS_IFY]  # agrees with the direct lookup


# --- deep descent --------------------------------------------------------------------

def test_deep_toggles_nested_visibility():
    '''`since` lives under the knows edge; only deep=True reaches it.'''
    g = _g()
    assert list(g.select(label=SINCE)) == []            # shallow: not a first-level assertion
    deep = list(g.select(label=SINCE, deep=True))
    assert len(deep) == 1 and deep[0].value == '2018'


def test_deep_origin_is_the_parent_assertion():
    '''A nested assertion's origin is its parent assertion, addressable by that parent's @id.'''
    g = _g()
    got = list(g.select(origin=CHUKS_IFY, deep=True))
    assert len(got) == 1 and got[0].label == SINCE
    assert got[0].origin is g.assertion_ids[CHUKS_IFY]


# --- live objects: the 4RDF remove-iterate pattern -----------------------------------

def test_select_yields_removable_objects():
    '''Results are the real objects, so a caller can delete them mid-iteration (snapshotted).'''
    g = _g()
    chuks = g[CHUKS]
    for a in g.select(origin=CHUKS, label=NAME):
        chuks.remove_property(a)
    assert list(g.select(origin=CHUKS, label=NAME)) == []
    assert len(list(g.select(origin=CHUKS))) == 3  # age + two knows edges remain


# --- object-identity constraints -----------------------------------------------------

def test_origin_and_target_accept_objects():
    '''A node/assertion object constrains by identity, not id.'''
    g = _g()
    chuks = g[CHUKS]
    assert len(list(g.select(origin=chuks))) == 5
    ify = g[IFY]
    to_ify = list(g.select(target=ify))
    assert len(to_ify) == 1 and to_ify[0].target is ify


def test_unknown_origin_id_selects_nothing():
    g = _g()
    assert list(g.select(origin=I('http://e.o/Nobody'))) == []


# --- match() back-compat (tuple projection over select) ------------------------------

def test_match_no_args_yields_all_tuples():
    '''match() widened to wildcard origin/label; still the (o, rel, target, ann) tuple.'''
    g = _g()
    rows = list(g.match())
    assert len(rows) == 6
    assert all(len(r) == 4 for r in rows)


def test_match_by_origin_matches_legacy_shape():
    g = _g()
    rows = list(g.match(CHUKS))
    assert len(rows) == 5
    assert all(o == CHUKS for (o, _r, _t, _a) in rows)
    # Edge tuples carry the target id; property tuples carry the string value.
    knows_targets = sorted(str(t) for (_o, r, t, _a) in rows if r == KNOWS)
    assert knows_targets == ['http://e.o/Ify', 'http://e.o/Nkiru']


def test_match_by_origin_and_label():
    g = _g()
    rows = list(g.match(CHUKS, NAME))
    assert sorted(t for (_o, _r, t, _a) in rows) == ['Charles', 'Chuks']
