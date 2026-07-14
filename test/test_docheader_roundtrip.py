# -*- coding: utf-8 -*-
# test_docheader_roundtrip.py
'''
The document node is a first-class node at the Onya Literate boundary (SPEC § Document Header,
ticket #26). Its `@docheader` bullets carry the same expressiveness as any node block —
`@as`, `@id`, nested/reified assertions, and edges — on both parse and serialize; only the
document id/type stay directive-driven (`@document` + implicit `onya:Document`).

    pytest -s test/test_docheader_roundtrip.py
'''

import warnings
from io import StringIO

from amara.iri import I

from onya.graph import graph
from onya.serial.literate import LiterateParser, write
from onya.terms import ONYA_INTERP, ONYA_DOCUMENT


DOC_IRI = I('http://e.o/doc')


def _parse(src):
    g = graph()
    LiterateParser().parse(src, g)
    return g


def _roundtrip(g):
    out = StringIO()
    write(g, out=out, document='http://e.o/doc', nodebase='http://e.o/', schema='https://schema.org/')
    text = out.getvalue()
    with warnings.catch_warnings():  # target-only nodes warn as empty blocks; irrelevant here
        warnings.simplefilter('ignore')
        return _parse(text), text


def _props(node):
    return {str(p.label).rsplit('/', 1)[-1]: p for p in node.properties}


def _edges(node):
    return {str(e.label).rsplit('/', 1)[-1]: e for e in node.edges}


HEADER = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''


# --- interpretations on document-node properties -------------------------------------

def test_inline_as_on_doc_property_round_trips():
    g = _parse(HEADER + '* metric: 5\n  * @as: number\n')
    p = _props(g[DOC_IRI])['metric']
    assert p.interp == ONYA_INTERP('number')
    g2, text = _roundtrip(g)
    assert '@as: number' in text
    assert _props(g2[DOC_IRI])['metric'].interp == ONYA_INTERP('number')


def test_interpretations_default_applies_to_doc_property():
    g = _parse(HEADER + '* @interpretations:\n    * mass: number\n* mass: 7\n')
    assert _props(g[DOC_IRI])['mass'].interp == ONYA_INTERP('number')


def test_inline_as_overrides_docheader_default_on_doc_property():
    src = HEADER + '* @interpretations:\n    * mass: number\n* mass: 7\n  * @as: text\n'
    g = _parse(src)
    assert _props(g[DOC_IRI])['mass'].interp == ONYA_INTERP('text')  # inline wins


# --- nesting, @id, edges on the document node ----------------------------------------

def test_nested_assertion_on_doc_property_round_trips():
    g = _parse(HEADER + '* title: Doc\n  * lang: en\n')
    title = _props(g[DOC_IRI])['title']
    assert _props(title)['lang'].value == 'en'
    g2, _ = _roundtrip(g)
    assert _props(_props(g2[DOC_IRI])['title'])['lang'].value == 'en'


def test_doc_edge_creates_target_and_round_trips():
    g = _parse(HEADER + '* about -> Thing\n')
    e = _edges(g[DOC_IRI])['about']
    assert e.target.id == I('http://e.o/Thing') and I('http://e.o/Thing') in g.nodes
    g2, text = _roundtrip(g)
    assert '* about -> Thing' in text
    assert _edges(g2[DOC_IRI])['about'].target.id == I('http://e.o/Thing')


def test_doc_assertion_id_addressable_as_edge_target():
    '''An @id on a doc-node edge names it; another doc-node edge can target that assertion.'''
    src = HEADER + '* rel -> Other\n  * @id: doc-rel\n* cites -> doc-rel\n'
    g = _parse(src)
    edges = _edges(g[DOC_IRI])
    assert edges['rel'].id == I('http://e.o/doc-rel')
    assert edges['cites'].target is edges['rel']  # edge targets the identified assertion
    assert g.assertion_ids[I('http://e.o/doc-rel')] is edges['rel']
    # survives a round trip
    g2, text = _roundtrip(g)
    assert '@id: doc-rel' in text
    edges2 = _edges(g2[DOC_IRI])
    assert edges2['cites'].target is edges2['rel']


# --- idempotence & regressions -------------------------------------------------------

def test_write_is_idempotent_over_rich_docheader():
    src = (HEADER + '* metric: 5\n  * @as: number\n* title: Doc\n  * lang: en\n'
           '* rel -> Other\n  * @id: doc-rel\n* cites -> doc-rel\n')
    g = _parse(src)
    _, text1 = _roundtrip(g)
    g2 = _parse(text1)
    _, text2 = _roundtrip(g2)
    assert text1 == text2


def test_directives_and_document_type_still_parse():
    '''Regression: directives keep working and the document node keeps its implicit type.'''
    src = ('# @docheader\n* @document: http://e.o/doc\n* @nodebase: http://e.o/\n'
           '* @schema: https://schema.org/\n* @iri:\n    * acme: https://acme.example/kg\n'
           '* title: Doc\n')
    g = _parse(src)
    doc = g[DOC_IRI]
    assert ONYA_DOCUMENT in doc.types
    assert _props(doc)['title'].value == 'Doc'
    # @document/@nodebase/@schema did not become stored assertions on the doc node
    assert set(_props(doc)) == {'title'}
