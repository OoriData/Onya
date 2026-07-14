# -*- coding: utf-8 -*-
# test_serial_nx.py
'''
Tests for onya.serial.nx — the networkx projection (to_networkx) and analytics
write-back (write_back). Extras-gated: skipped cleanly when networkx is absent.

    pytest -s test/test_serial_nx.py
'''

from io import StringIO

import pytest

networkx = pytest.importorskip('networkx')  # noqa: E402 - skip the whole module without the extra

from amara.iri import I  # noqa: E402

from onya.graph import graph  # noqa: E402
from onya.serial import nx  # noqa: E402
from onya.serial.literate import LiterateParser, write  # noqa: E402
from onya.terms import ONYA_INTERP  # noqa: E402
from onya.interp import value_of  # noqa: E402


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
  * @as: number
* rating: high
  * @as: <http://e.o/vocab/grade>
* knows -> Ify
  * since: 2018
* knows -> Ify

# Ify [Person]

* name: Ify

# Nkiru [Person]

* asserts -> Ify
  * @id: chuks-claim

# ReviewNote

* disputes -> chuks-claim
'''

CHUKS = 'http://e.o/Chuks'
IFY = 'http://e.o/Ify'
NAME = 'https://schema.org/name'
AGE = 'https://schema.org/age'
RATING = 'https://schema.org/rating'
KNOWS = 'https://schema.org/knows'
SINCE = 'https://schema.org/since'


def _g(doc=DOC):
    g = graph()
    LiterateParser().parse(doc, g)
    return g


# --- node projection -----------------------------------------------------------------

def test_node_ids_and_types():
    mg = nx.to_networkx(_g())
    assert isinstance(mg, networkx.MultiDiGraph)
    assert CHUKS in mg.nodes  # keyed by full IRI string
    assert mg.nodes[CHUKS]['types'] == ('https://schema.org/Person',)  # tuple of str IRIs


def test_multivalued_property_is_a_list():
    '''Multi-valued properties are honest lists, never last-wins.'''
    mg = nx.to_networkx(_g())
    assert sorted(mg.nodes[CHUKS][NAME]) == ['Charles', 'Chuks']


# --- edge projection -----------------------------------------------------------------

def test_edge_label_and_properties_as_attrs():
    mg = nx.to_networkx(_g())
    # The since-bearing knows edge carries its first-level property as a list attr.
    datas = list(mg.get_edge_data(CHUKS, IFY).values())
    labels = {d['label'] for d in datas}
    assert labels == {KNOWS}
    since_edges = [d for d in datas if SINCE in d]
    assert len(since_edges) == 1 and since_edges[0][SINCE] == ['2018']


def test_parallel_edges_distinct_unmerged_then_collapse_on_merge():
    '''Two same-skeleton knows occurrences stay distinct (auto keys); merge collapses them.'''
    mg = nx.to_networkx(_g())
    assert mg.number_of_edges(CHUKS, IFY) == 2  # unmerged: distinct occurrences preserved

    merged = nx.to_networkx(_g().merge())
    assert merged.number_of_edges(CHUKS, IFY) == 1  # normalized projection


def test_identified_assertion_edge_target_skipped():
    '''An edge whose target is an identified assertion is skipped (with a warning), no error.'''
    with pytest.warns(UserWarning, match='identified assertions skipped'):
        mg = nx.to_networkx(_g())
    # ReviewNote survives as a node; its only edge (disputes -> chuks-claim) is dropped.
    assert 'http://e.o/ReviewNote' in mg.nodes
    assert mg.out_degree('http://e.o/ReviewNote') == 0


# --- interpretation hook -------------------------------------------------------------

def test_apply_interps_converts_number_and_falls_back_on_unknown():
    raw = nx.to_networkx(_g())
    assert raw.nodes[CHUKS][AGE] == ['40']  # default: raw string

    typed = nx.to_networkx(_g(), apply_interps=True)
    assert typed.nodes[CHUKS][AGE] == [40]  # @as: number -> Python int
    # Unknown interpretation is non-strict: the raw string, not an exception.
    assert typed.nodes[CHUKS][RATING] == ['high']


# --- write_back ----------------------------------------------------------------------

def test_write_back_writes_and_counts():
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    n = nx.write_back(g, metric, {CHUKS: 0.5, IFY: 0.0})
    assert n == 2
    assert [p.value for p in g.select(origin=I(CHUKS), label=metric)] == ['0.5']


def test_write_back_replace_is_idempotent():
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    nx.write_back(g, metric, {CHUKS: 0.5})
    nx.write_back(g, metric, {CHUKS: 0.7})  # replace=True default
    props = list(g[I(CHUKS)].getprop(metric))
    assert len(props) == 1 and props[0].value == '0.7'


def test_write_back_accumulates_when_not_replacing():
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    nx.write_back(g, metric, {CHUKS: 0.5}, replace=False)
    nx.write_back(g, metric, {CHUKS: 0.7}, replace=False)
    assert sorted(p.value for p in g[I(CHUKS)].getprop(metric)) == ['0.5', '0.7']


def test_write_back_interp_round_trips_through_value_of():
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    nx.write_back(g, metric, {CHUKS: 0.5, IFY: 3}, interp=ONYA_INTERP('number'))
    by_id = {str(p.origin.id): p for p in g.select(label=metric)}
    assert value_of(by_id[CHUKS]) == 0.5 and value_of(by_id[IFY]) == 3
    assert by_id[CHUKS].interp == ONYA_INTERP('number')  # the contract rides along


def test_write_back_skips_unknown_node_ids():
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    n = nx.write_back(g, metric, {CHUKS: 0.5, 'http://e.o/Nobody': 9.9})
    assert n == 1  # the unknown id is skipped, not an error


# --- full round trip through Literate ------------------------------------------------

def test_round_trip_survives_serialize_reparse():
    '''Annotate, write Literate, re-parse: values and interps survive.'''
    g = _g()
    metric = 'http://e.o/analytics/centrality'
    # Annotate entity nodes (not the document node, whose docheader bullets don't carry @as).
    nx.write_back(g, metric, {CHUKS: 0.5, IFY: 3}, interp=ONYA_INTERP('number'))

    out = StringIO()
    write(g, out=out, document='http://e.o/doc', nodebase='http://e.o/', schema='https://schema.org/')
    reparsed = _g(out.getvalue())

    original = {str(p.origin.id): value_of(p) for p in g.select(label=metric)}
    survived = {str(p.origin.id): value_of(p) for p in reparsed.select(label=metric)}
    assert survived == original
    assert all(p.interp == ONYA_INTERP('number') for p in reparsed.select(label=metric))
