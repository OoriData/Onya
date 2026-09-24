# -*- coding: utf-8 -*-
# test/test_graph_prefixes.py
'''
CURIE-keyed accessors: `graph.prefixes` populated from the parse, label arguments as full
IRI / CURIE / bare `@schema` name, unknown prefixes raising, and prefix merging on union.

    pytest -s test/test_graph_prefixes.py
'''

import warnings

import pytest
from amara.iri import I

from onya import ONYA_BASEIRI
from onya.graph import UnknownPrefixError, graph, resolve_label
from onya.serial import literate

P = 'http://example.org/people/'

DOC = '''# @docheader
* @nodebase: http://example.org/people/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab/

# ada [Person]
* name: Ada Lovelace
* ex:name: AAL
* worksFor -> aec
    * ex:since: 1843
'''


@pytest.fixture
def g():
    return literate.read(DOC).graph


def test_prefixes_populated_from_parse(g):
    assert g.prefixes['ex'] == 'http://example.org/vocab'
    assert g.prefixes['schema'] == 'https://schema.org'


def test_curie_bare_and_full_iri_agree(g):
    ada = g[P + 'ada']
    assert ada.any_prop_value('schema:name') == 'Ada Lovelace'
    assert ada.any_prop_value('name') == 'Ada Lovelace'
    assert ada.any_prop_value('https://schema.org/name') == 'Ada Lovelace'
    assert ada.any_prop_value(I('https://schema.org/name')) == 'Ada Lovelace'
    assert ada.any_prop_value('<schema:name>') == 'Ada Lovelace'


def test_same_local_name_different_vocab_not_conflated(g):
    ada = g[P + 'ada']
    assert ada.any_prop_value('ex:name') == 'AAL'
    assert ada.any_prop_value('schema:name') == 'Ada Lovelace'


def test_edges_nested_and_queries(g):
    ada = g[P + 'ada']
    [e] = ada.getedge('schema:worksFor')
    assert e.target.id == P + 'aec'
    assert e.any_prop_value('ex:since') == '1843'   # nested assertion finds the graph too
    assert [a.value for a in g.select(label='ex:name')] == ['AAL']
    assert [n.id for n in g.typematch('schema:Person')] == [P + 'ada']


def test_unknown_prefix_raises(g):
    with pytest.raises(UnknownPrefixError):
        g[P + 'ada'].any_prop_value('foaf:name')
    with pytest.raises(UnknownPrefixError):
        list(g.select(label='foaf:name'))


def test_resolve_label_rules():
    pre = {'schema': 'https://schema.org', 'ex': 'http://example.org/v/'}
    assert resolve_label('ex:a', pre) == 'http://example.org/v/a'
    assert resolve_label('a', pre) == 'https://schema.org/a'
    assert resolve_label('a', None) == 'a'                     # no @schema: unchanged
    assert resolve_label('urn:isbn:123', pre) == 'urn:isbn:123'
    assert resolve_label('http://x.org/a', None) == 'http://x.org/a'
    assert resolve_label('@source', None) == ONYA_BASEIRI('source')


def test_detached_node_has_no_prefixes():
    from onya.graph import node
    n = node(I('x'))
    n.add_property(I('http://x.org/a'), 'v')
    assert n.any_prop_value('http://x.org/a') == 'v'
    with pytest.raises(UnknownPrefixError):
        n.any_prop_value('ex:a')


def test_node_holds_graph_weakly():
    import gc
    import weakref
    g = literate.read(DOC).graph
    ada = g[P + 'ada']
    assert ada._graph is g
    gref = weakref.ref(g)
    del g
    gc.collect()
    assert gref() is None             # the node did not keep its graph alive
    assert ada._graph is None
    assert ada.any_prop_value('https://schema.org/name') == 'Ada Lovelace'  # full IRIs still fine
    with pytest.raises(UnknownPrefixError, match='no longer alive'):
        ada.any_prop_value('schema:name')


def test_union_merges_prefixes_and_warns_on_clash():
    a = graph(prefixes={'ex': 'http://a.org/', 'same': 'http://s.org/'})
    b = graph(prefixes={'ex': 'http://b.org/', 'alias': 'http://s.org/', 'new': 'http://n.org/'})
    with pytest.warns(UserWarning, match="Prefix 'ex' clash"):
        a.union(b)
    assert a.prefixes == {'ex': 'http://a.org/', 'same': 'http://s.org/',
                          'alias': 'http://s.org/', 'new': 'http://n.org/'}


def test_union_same_binding_no_warning():
    a = graph(prefixes={'ex': 'http://a.org/'})
    b = graph(prefixes={'ex': 'http://a.org'})  # trailing-slash difference only
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        a.union(b)


def test_parse_into_existing_graph_folds_prefixes():
    g = graph(prefixes={'ex': 'http://other.org/'})
    with pytest.warns(UserWarning, match='clash'):
        literate.read(DOC, g)
    assert g.prefixes['ex'] == 'http://other.org/'
    assert g.prefixes['schema'] == 'https://schema.org'
