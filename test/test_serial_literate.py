# -*- coding: utf-8 -*-
# test_serial_literate.py
'''
Test Onya literate serializer

pytest -s test/py/test_serial_literate.py
'''

# import functools

# Requires pytest-mock
import warnings

import pytest

from amara.iri import I

from onya.graph import graph
#from onya.serial.literate import *
from io import StringIO

from onya.serial.literate import LiterateParser, NamespaceBaseError, SchemaPrefixConflict, read, write
from onya.serial._literate_parse import doc_info, expand_iri
from onya.util import compact_iri, join_namespace # , namespace_for_curie
from onya import LITERAL, ONYA_BASEIRI


def _prop_value(v):
    return str(v) if isinstance(v, LITERAL) else v

# T = I('http://example.org')
T = I('http://e.o')

TFA_1 = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# TFA [Book]

* name: Things Fall Apart
* image: http://example.org/classics/tfa-book-cover.jpg
* isbn: 9781841593272
* author -> CAchebe
* publisher -> Heinemann
  * when: 1958
  * where: London  <!-- Should properly be reified to a node, but in post-processing -->
    * country: UK

# CAchebe [Person]

* name: Chinụalụmọgụ Achebe
* birthDate: 1930

# Heinemann [Organization]

* name: William Heinemann Ltd.
* birthDate: 1930
'''


# @pytest.mark.parametrize('doc', DOC_CASES)
def test_parse_tfa_1():
    g = graph()
    op = LiterateParser()
    result = op.parse(TFA_1, g)

    # Should have document node + TFA + CAchebe + Heinemann
    assert len(result.nodes_added) == 4
    assert result.doc_iri == 'http://e.o/doc'
    # Verify the main entities exist
    assert 'http://e.o/TFA' in g
    assert 'http://e.o/CAchebe' in g
    assert 'http://e.o/Heinemann' in g


def test_parse_tfa_expanded():
    '''Test the expanded Things Fall Apart example with docheader'''
    from onya.graph import graph
    from onya.serial.literate import LiterateParser
    
    # Read the file
    with open('test/resource/schemaorg/thingsfallapart.onya') as f:
        content = f.read()
    
    # Create a graph and parse into it
    g = graph()
    op = LiterateParser()
    result = op.parse(content, g)
    doc_iri = result.doc_iri
    
    # Verify we got document metadata
    assert doc_iri == 'http://example.org/classics/things-fall-apart'
    # Should have parsed multiple nodes
    assert len(g) > 0
    # Check that document node exists
    assert doc_iri in g


def test_nodebase_falls_back_to_document():
    '''
    If @nodebase is omitted, node ID resolution falls back to @document.

    This must apply both to node headers (origins) and edge targets.
    '''
    onya_text = '''\
# @docheader
* @document: http://example.org/base/
* @schema: https://schema.org/

# A [Person]
* name: Alice
* knows -> B
'''
    g = graph()
    op = LiterateParser()
    result = op.parse(onya_text, g)

    assert result.doc_iri == 'http://example.org/base/'
    assert 'http://example.org/base/A' in g
    assert 'http://example.org/base/B' in g  # created via edge target resolution


def test_document_source_assertions():
    '''
    When enabled, every created assertion gets an @source sub-property whose
    value is the source document IRI.
    '''
    onya_text = '''\
# @docheader
* @document: http://example.org/doc1#
* @schema: https://schema.org/

# A [Person]
* name: Alice
* knows -> B
  * since: 2020
'''
    g = graph()
    op = LiterateParser(document_source_assertions=True)
    result = op.parse(onya_text, g)

    source_rel = ONYA_BASEIRI('source')
    a = g['http://example.org/doc1#A']

    # Top-level property assertions should have @source in their annotation dict
    saw_name = False
    saw_knows = False
    for o, rel, t, ann in g.match(a.id):
        if str(rel) == 'https://schema.org/name':
            saw_name = True
            assert ann.get(source_rel) == result.doc_iri
        if str(rel) == 'https://schema.org/knows':
            saw_knows = True
            assert ann.get(source_rel) == result.doc_iri
    assert saw_name
    assert saw_knows

    # Nested assertions should also get @source (here: the 'since' property on the knows edge)
    knows_edges = list(a.traverse('https://schema.org/knows'))
    assert len(knows_edges) == 1
    knows = knows_edges[0]
    since_props = list(knows.getprop('https://schema.org/since'))
    assert len(since_props) == 1
    since_prop = since_props[0]
    src_props = list(since_prop.getprop(source_rel))
    assert len(src_props) == 1
    assert src_props[0].value == result.doc_iri


def test_document_node_has_type():
    '''
    Verify document nodes automatically get onya:Document type.

    When a document is created via @document directive, it should
    receive the onya:Document type in addition to any properties.
    '''
    from onya.terms import ONYA_DOCUMENT

    onya_text = '''\
# @docheader
* @document: http://example.org/my-doc
* title: Test Document
* @schema: https://schema.org/

# Node1 [Person]
* name: Alice
'''
    g = graph()
    op = LiterateParser()
    result = op.parse(onya_text, g)

    # Verify document node exists and has the correct IRI
    assert result.doc_iri == 'http://example.org/my-doc'
    assert result.doc_iri in g

    # Get the document node
    doc_node = g[result.doc_iri]

    # Verify it has the onya:Document type
    assert ONYA_DOCUMENT in doc_node.types
    assert len(doc_node.types) == 1

    # Verify it has properties (the title)
    title_props = list(doc_node.getprop('https://schema.org/title'))
    assert len(title_props) == 1
    assert title_props[0].value == 'Test Document'


def test_typebase_directive():
    '''
    Test @typebase directive for cases where types need different base than properties.
    
    When @typebase is specified, types should resolve using it instead of @schema.
    '''
    onya_text = '''\
# @docheader
* @document: http://example.org/test-doc
* @nodebase: http://example.org/entities/
* @schema: https://schema.org/
* @typebase: http://example.org/types/

# Alice [Person]
* name: Alice Smith
* knows -> Bob

# Bob [Person]
* name: Bob Jones
'''
    g = graph()
    op = LiterateParser()
    _ = op.parse(onya_text, g)

    alice = g['http://example.org/entities/Alice']
    bob = g['http://example.org/entities/Bob']

    # Types should use @typebase
    assert 'http://example.org/types/Person' in alice.types
    assert 'http://example.org/types/Person' in bob.types

    # Properties should still use @schema
    name_props = list(alice.getprop('https://schema.org/name'))
    assert len(name_props) == 1
    assert name_props[0].value == 'Alice Smith'

    # Edges should still use @schema
    knows_edges = list(alice.traverse('https://schema.org/knows'))
    assert len(knows_edges) == 1
    assert knows_edges[0].target == bob


def test_join_namespace_avoids_duplicate_slash():
    assert join_namespace('https://acme.example/kg/schema', 'Client') == (
        'https://acme.example/kg/schema/Client'
    )
    assert join_namespace('https://acme.example/kg/schema/', 'Client') == (
        'https://acme.example/kg/schema/Client'
    )
    assert join_namespace('https://schema.org/', 'name') == 'https://schema.org/name'
    assert join_namespace('http://example.org/vocab#', 'Thing') == 'http://example.org/vocab#Thing'


def test_schema_autoregister_from_schema_directive():
    onya_text = '''\
# @docheader
* @document: https://acme.example/doc
* @nodebase: https://acme.example/
* @schema: https://schema.org/
* @iri:
    * acme: https://acme.example/kg/schema

# N [Thing]
* name: X
* schema:name: X
'''
    g = graph()
    LiterateParser().parse(onya_text, g)
    n = g['https://acme.example/N']
    assert list(n.getprop('https://schema.org/name'))[0].value == 'X'


def test_schema_prefix_conflict_raises():
    onya_text = '''\
# @docheader
* @schema: https://schema.org/
* @iri:
    * schema: https://vocab.example.org/core

# N [Thing]
* name: X
'''
    g = graph()
    with pytest.raises(SchemaPrefixConflict):
        LiterateParser().parse(onya_text, g)


def test_compact_iri_bare_schema_and_bracket():
    prefixes = {
        'acme': 'https://acme.example/kg/schema',
        'schema': 'https://schema.org',
    }
    assert compact_iri('https://schema.org/name', prefixes) == 'name'
    assert compact_iri('https://acme.example/kg/schema/contactPoint', prefixes) == (
        'acme:contactPoint'
    )
    assert compact_iri(
        'https://acme.example/kg/schema/contactPoint', prefixes, bracket=True
    ) == '<acme:contactPoint>'


ACME_CURIE_ONYA = '''\
# @docheader

* @document: https://acme.example/pulse/kg/sample
* title: Acme Corp (Acme client)
* @nodebase: https://acme.example/pulse/kg/sample/
* @schema: https://schema.org/
* @iri:
    * acme: https://acme.example/kg/schema

# Acme [<acme:Client>]

* name: ACME Corporation
* url: https://www.acme.example/
* <acme:contactPoint> -> acme-cp-main

# acme-cp-main [ContactPoint]

* contactType: main
* name: Jane Doe
* email: jane.doe@acme.example
'''


def test_write_roundtrip_curie():
    g1 = graph()
    LiterateParser().parse(ACME_CURIE_ONYA, g1)

    buf = StringIO()
    write(
        g1,
        buf,
        document='https://acme.example/pulse/kg/sample',
        nodebase='https://acme.example/pulse/kg/sample/',
        schema='https://schema.org/',
        prefixes={'acme': 'https://acme.example/kg/schema'},
    )
    text2 = buf.getvalue()

    g2 = graph()
    LiterateParser().parse(text2, g2)

    assert set(g2.nodes.keys()) == set(g1.nodes.keys())
    for nid in g1.nodes:
        n1, n2 = g1[nid], g2[nid]
        assert n1.types == n2.types
        assert {(str(p.label), _prop_value(p.value)) for p in n1.properties} == {
            (str(p.label), _prop_value(p.value)) for p in n2.properties
        }
        assert {
            (str(e.label), e.target.id) for e in n1.edges
        } == {(str(e.label), e.target.id) for e in n2.edges}


def test_write_bracket_curie_flag():
    g = graph()
    LiterateParser().parse(ACME_CURIE_ONYA, g)
    buf = StringIO()
    write(
        g,
        buf,
        document='https://acme.example/pulse/kg/sample',
        nodebase='https://acme.example/pulse/kg/sample/',
        schema='https://schema.org/',
        prefixes={'acme': 'https://acme.example/kg/schema'},
        bracket_curie=True,
    )
    assert '<acme:contactPoint>' in buf.getvalue()


def test_expand_curie_from_iri_block():
    d = doc_info()
    d.iris = {
        'acme': 'https://acme.example/kg/schema',
        'schema': 'https://schema.org',
    }
    d.schemabase = 'https://schema.org/'

    assert expand_iri('acme:Client', d.schemabase, doc=d) == I(
        'https://acme.example/kg/schema/Client'
    )
    assert expand_iri('<acme:contactPoint>', d.schemabase, doc=d) == I(
        'https://acme.example/kg/schema/contactPoint'
    )
    assert expand_iri('name', d.schemabase, doc=d) == I('https://schema.org/name')


def test_parse_curie_acme_client_example():
    '''Parse Acme Corp example using @iri CURIE prefixes (acme:; schema: from @schema).'''
    onya_text = ACME_CURIE_ONYA.replace(
        'jane.doe@acme.example',
        'jane.doe@acme.example\n* telephone: +1-555-0100\n* url: https://www.linkedin.com/in/janedoe',
    ).replace(
        '* <acme:contactPoint> -> acme-cp-main',
        '* description: Engineering services client.\n* <acme:contactPoint> -> acme-cp-main',
    )
    g = graph()
    op = LiterateParser()
    result = op.parse(onya_text, g)

    assert result.doc_iri == 'https://acme.example/pulse/kg/sample'
    acme = g['https://acme.example/pulse/kg/sample/Acme']
    assert I('https://acme.example/kg/schema/Client') in acme.types

    name_props = list(acme.getprop('https://schema.org/name'))
    assert len(name_props) == 1
    assert name_props[0].value == 'ACME Corporation'

    cp_edges = list(acme.traverse('https://acme.example/kg/schema/contactPoint'))
    assert len(cp_edges) == 1
    assert cp_edges[0].target.id == 'https://acme.example/pulse/kg/sample/acme-cp-main'

    cp = cp_edges[0].target
    assert I('https://schema.org/ContactPoint') in cp.types
    assert list(cp.getprop('https://schema.org/email'))[0].value == 'jane.doe@acme.example'


def test_unicode_arrow_edge():
    '''U+2192 → is accepted as a synonym for -> in edge assertions.'''
    text = '''# @docheader
* @document: http://example.org/d
* @nodebase: http://example.org/
* @schema: https://schema.org/

# A [Person]
* name: Alice
* knows → B

# B [Person]
* name: Bob
'''
    g = graph()
    read(text, g)
    a = g['http://example.org/A']
    edges = list(a.traverse('https://schema.org/knows'))
    assert len(edges) == 1
    assert edges[0].target.id == 'http://example.org/B'


def test_read_shim_roundtrip():
    '''Public read() API parses text or file-like objects; survives a write → read round-trip.'''
    g1 = graph()
    result_str = read(ACME_CURIE_ONYA, g1)
    assert result_str.doc_iri == 'https://acme.example/pulse/kg/sample'
    assert set(g1.nodes.keys()) == set(result_str.graph.nodes.keys())

    buf = StringIO()
    write(
        g1,
        buf,
        document='https://acme.example/pulse/kg/sample',
        nodebase='https://acme.example/pulse/kg/sample/',
        schema='https://schema.org/',
        prefixes={'acme': 'https://acme.example/kg/schema'},
    )
    buf.seek(0)
    g2 = graph()
    result_fp = read(buf, g2)
    assert result_fp.doc_iri == 'https://acme.example/pulse/kg/sample'
    assert set(g2.nodes.keys()) == set(g1.nodes.keys())


# A base missing its trailing separator: bare names concatenate, mashing the IRI.
_NO_SEP_NODEBASE = '''\
# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/g
* @schema: http://e.o/s/

# MyNode [Thing]
* name: X
'''


def test_namespace_base_missing_separator_warns_by_default():
    '''Deprecation window: a separator-less base warns but still parses (mashed IRI).'''
    g = graph()
    with pytest.warns(DeprecationWarning, match='@nodebase'):
        LiterateParser().parse(_NO_SEP_NODEBASE, g)
    # Concatenation, not separator insertion: the id mashes onto the base.
    assert I('http://e.o/gMyNode') in g.nodes


def test_namespace_base_missing_separator_strict_raises():
    '''strict_namespace_bases=True rejects the same input with NamespaceBaseError.'''
    g = graph()
    with pytest.raises(NamespaceBaseError):
        LiterateParser(strict_namespace_bases=True).parse(_NO_SEP_NODEBASE, g)


@pytest.mark.parametrize('base', ['http://e.o/', 'http://e.o/v#', 'http://e.o/q?'])
def test_namespace_base_with_separator_ok(base, recwarn):
    '''Bases ending in `/`, `#`, or `?` neither warn nor raise, under strict or not.'''
    onya_text = f'''\
# @docheader
* @document: http://e.o/doc
* @nodebase: {base}
* @schema: {base}

# N [Thing]
* name: X
'''
    g = graph()
    LiterateParser(strict_namespace_bases=True).parse(onya_text, g)
    assert not [w for w in recwarn.list if issubclass(w.category, DeprecationWarning)]


def test_namespace_base_check_skips_document_fallback():
    '''The @nodebase->@document fallback is out of scope: a separator-less @document
    (and no explicit @nodebase) must not warn or raise.'''
    onya_text = '''\
# @docheader
* @document: http://e.o/doc
* @schema: http://e.o/s/

# N [Thing]
* name: X
'''
    g = graph()
    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        LiterateParser(strict_namespace_bases=True).parse(onya_text, g)


# No @nodebase + a separator-less @document: relative ids resolve off @document.
_DOC_FALLBACK = '''\
# @docheader
* @document: http://e.o/doc
* @schema: http://e.o/s/

# A [Person]
* name: Alice
* knows -> B
'''


def test_document_fallback_uses_implicit_hash_separator():
    '''Serialization rule: relative ids get an implicit `#`, silently, for node headers
    and edge targets alike.'''
    g = graph()
    with warnings.catch_warnings():
        warnings.simplefilter('error')  # silent by default — any warning would fail here
        LiterateParser().parse(_DOC_FALLBACK, g)
    assert I('http://e.o/doc#A') in g.nodes
    assert I('http://e.o/doc#B') in g.nodes  # edge target resolves the same way


def test_document_fallback_warns_when_flag_set():
    '''warn_implicit_doc_ids surfaces each implicit `#` construction.'''
    g = graph()
    with pytest.warns(UserWarning, match='implicit `#`'):
        LiterateParser(warn_implicit_doc_ids=True).parse(_DOC_FALLBACK, g)


def test_document_fallback_with_separator_no_implicit_hash():
    '''A @document already ending in a separator concatenates directly: no `#`, no warning
    even with the flag on.'''
    onya_text = '''\
# @docheader
* @document: http://e.o/doc/
* @schema: http://e.o/s/

# A [Person]
* name: Alice
'''
    g = graph()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        LiterateParser(warn_implicit_doc_ids=True).parse(onya_text, g)
    assert I('http://e.o/doc/A') in g.nodes


_EMPTY_BLOCK_DOC = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# A [Thing]

* rel -> B

# B
'''


def test_empty_block_parses_with_warning():
    '''A node block with no type or assertions now parses, and warns by default.'''
    g = graph()
    with pytest.warns(UserWarning, match='empty'):
        LiterateParser().parse(_EMPTY_BLOCK_DOC, g)
    assert I('http://e.o/B') in g.nodes
    # The edge into the (empty) block still resolves to that node
    edges = list(g['http://e.o/A'].traverse('http://e.o/rel'))
    assert len(edges) == 1
    assert edges[0].target is g['http://e.o/B']


def test_empty_block_warning_can_be_silenced():
    '''warn_empty_blocks=False suppresses the empty-block warning (turned into an error here).'''
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        LiterateParser(warn_empty_blocks=False).parse(_EMPTY_BLOCK_DOC, graph())


def test_typed_block_without_assertions_not_warned():
    '''A block with a type but no assertions is not "empty" (the type is content): no warning.'''
    onya_text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# B [Thing]
'''
    g = graph()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        LiterateParser().parse(onya_text, g)
    assert I('http://e.o/Thing') in g['http://e.o/B'].types


def test_deep_nesting_roundtrips():
    '''Nested edges and depth > 1 now round-trip (previously the reader collapsed depth and
    the writer dropped nested edges).'''
    onya_text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# Sale [Transaction]

* item -> Widget
  * price: 10
    * currency: USD
  * warranty -> WarrantyDoc
    * months: 12

# Widget [Product]

* name: Widget

# WarrantyDoc [Document]

* name: Warranty
'''
    g = graph()
    LiterateParser().parse(onya_text, g)

    item = list(g['http://e.o/Sale'].traverse('http://e.o/item'))[0]
    # price is nested under the item edge; currency is nested under price (depth 3)
    price = list(item.getprop('http://e.o/price'))[0]
    assert price.value == '10'
    assert list(price.getprop('http://e.o/currency'))[0].value == 'USD'
    # warranty is a nested *edge* under the item edge, with its own nested property
    warranty = list(item.getedge('http://e.o/warranty'))[0]
    assert warranty.target is g['http://e.o/WarrantyDoc']
    assert list(warranty.getprop('http://e.o/months'))[0].value == '12'

    # Round-trip preserves the nested edge and the depth-3 property
    buf = StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='http://e.o/')
    g2 = graph()
    LiterateParser().parse(buf.getvalue(), g2)
    item2 = list(g2['http://e.o/Sale'].traverse('http://e.o/item'))[0]
    price2 = list(item2.getprop('http://e.o/price'))[0]
    assert list(price2.getprop('http://e.o/currency'))[0].value == 'USD'
    warranty2 = list(item2.getedge('http://e.o/warranty'))[0]
    assert warranty2.target is g2['http://e.o/WarrantyDoc']
    assert list(warranty2.getprop('http://e.o/months'))[0].value == '12'
