# -*- coding: utf-8 -*-
# test_serial_literate.py
'''
Test Onya literate serializer

pytest -s test/py/test_serial_literate.py
'''

# import functools

# Requires pytest-mock
# import pytest

from amara.iri import I

from onya.graph import graph
#from onya.serial.literate import *
from onya.serial.literate_lex import LiterateParser
from onya import ONYA_BASEIRI

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
    from onya.serial.literate_lex import LiterateParser
    
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
