# -*- coding: utf-8 -*-
# test_provenance.py
'''
Tests for the `@method`/`@confidence` reserved provenance vocabulary (SPEC: Optional
assertion provenance) and its accessors in `onya.provenance`.

    pytest -s test/test_provenance.py
'''

from amara.iri import I

from onya.graph import graph
from onya.serial.literate import LiterateParser
from onya.terms import ONYA_METHOD_REL, ONYA_CONFIDENCE_REL, ONYA_INTERP
from onya.provenance import list_provenance, highest_confidence


VALUE_REL = I('https://schema.org/value')
XBRL_METHOD = I('https://example.org/xbrl-tag')
NER_METHOD = I('https://example.org/gliner-ner')

DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''


def _parse(text: str) -> graph:
    g = graph()
    LiterateParser().parse(text, g)
    return g


# --- authoring: zero parser changes needed, in Literate and via the programmatic API ----

def test_method_confidence_authorable_in_literate():
    '''@method/@confidence resolve through the generic @-vocabulary path, no parser support.'''
    text = DOCHEADER + '''
# Filing [Thing]

* value: "5323000000"
    * @method -> XbrlTag
        * @confidence: 1.0
            * @as: number
'''
    g = _parse(text)
    filing = g[I('http://e.o/Filing')]
    (value_prop,) = list(filing.getprop(VALUE_REL))
    entries = list_provenance(value_prop)
    assert len(entries) == 1
    assert entries[0].method == 'http://e.o/XbrlTag'
    assert entries[0].confidence == 1.0


def test_method_confidence_authorable_via_api():
    '''Same shape, built programmatically — the way real extraction code would write it.'''
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    method_edge = value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD))
    method_edge.add_property(ONYA_CONFIDENCE_REL, '1.0', interp=ONYA_INTERP('number'))

    entries = list_provenance(value_prop)
    assert len(entries) == 1
    assert entries[0].method == str(XBRL_METHOD)
    assert entries[0].confidence == 1.0
    assert entries[0].assertion is method_edge


# --- list_provenance: 0, 1, N entries -----------------------------------------------

def test_list_provenance_empty_when_untagged():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    assert list_provenance(value_prop) == []


def test_list_provenance_multiple_corroborating_methods():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')

    xbrl_edge = value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD))
    xbrl_edge.add_property(ONYA_CONFIDENCE_REL, '1.0')

    ner_edge = value_prop.add_edge(ONYA_METHOD_REL, g.node(NER_METHOD))
    ner_edge.add_property(ONYA_CONFIDENCE_REL, '0.87')

    entries = {e.method: e.confidence for e in list_provenance(value_prop)}
    assert entries == {str(XBRL_METHOD): 1.0, str(NER_METHOD): 0.87}


def test_confidence_without_as_number_still_parses():
    '''get_confidence never requires @as: number — it just tries float() on the raw string.'''
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    method_edge = value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD))
    method_edge.add_property(ONYA_CONFIDENCE_REL, '0.5')  # no @as at all
    (entry,) = list_provenance(value_prop)
    assert entry.confidence == 0.5


def test_unparseable_confidence_is_none():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    method_edge = value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD))
    method_edge.add_property(ONYA_CONFIDENCE_REL, 'high')  # not a float
    (entry,) = list_provenance(value_prop)
    assert entry.method == str(XBRL_METHOD)
    assert entry.confidence is None


def test_method_without_confidence_is_none():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD))  # no nested @confidence at all
    (entry,) = list_provenance(value_prop)
    assert entry.confidence is None


# --- highest_confidence: read-time opt-in view, never mutates -----------------------

def test_highest_confidence_picks_the_best():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD)).add_property(ONYA_CONFIDENCE_REL, '1.0')
    value_prop.add_edge(ONYA_METHOD_REL, g.node(NER_METHOD)).add_property(ONYA_CONFIDENCE_REL, '0.87')

    best = highest_confidence(value_prop)
    assert best.method == str(XBRL_METHOD)
    assert best.confidence == 1.0
    # never destructive: both entries are still there afterwards
    assert len(list_provenance(value_prop)) == 2


def test_highest_confidence_none_when_nothing_parseable():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    value_prop.add_edge(ONYA_METHOD_REL, g.node(XBRL_METHOD)).add_property(ONYA_CONFIDENCE_REL, 'unknown')
    assert highest_confidence(value_prop) is None


def test_highest_confidence_none_when_untagged():
    g = graph()
    n = g.node(I('http://e.o/Filing'))
    value_prop = n.add_property(VALUE_REL, '5323000000')
    assert highest_confidence(value_prop) is None


# --- merge: the structural reason @confidence nests under @method, not beside it ----

def test_merge_keeps_both_corroborating_pairs_intact():
    '''
    Regression test for the sibling-vs-nested structural fix: two graphs independently
    corroborating the same fact must merge into ONE value assertion with TWO distinct
    @method entries, each still carrying its OWN @confidence — not four flattened
    siblings with the method/confidence pairing lost.
    '''
    g1 = graph()
    n1 = g1.node(I('http://e.o/Filing'))
    v1 = n1.add_property(VALUE_REL, '5323000000')
    v1.add_edge(ONYA_METHOD_REL, g1.node(XBRL_METHOD)).add_property(ONYA_CONFIDENCE_REL, '1.0')

    g2 = graph()
    n2 = g2.node(I('http://e.o/Filing'))
    v2 = n2.add_property(VALUE_REL, '5323000000')
    v2.add_edge(ONYA_METHOD_REL, g2.node(NER_METHOD)).add_property(ONYA_CONFIDENCE_REL, '0.87')

    g1.union(g2)

    merged_filing = g1[I('http://e.o/Filing')]
    (merged_value,) = list(merged_filing.getprop(VALUE_REL))  # Rule 2: same skeleton -> one property
    entries = {e.method: e.confidence for e in list_provenance(merged_value)}
    assert entries == {str(XBRL_METHOD): 1.0, str(NER_METHOD): 0.87}
