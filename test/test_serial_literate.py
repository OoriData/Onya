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

from onya.graph import node, graph, property_, edge
#from onya.serial.literate import *
from onya.serial.litparse_util import parser

# T = I('http://example.org')
T = I('http://e.o')

TFA_1 = '''\
# http://e.o/TFA [http://e.o/Book]

* http://e.o/name: Things Fall Apart
* http://e.o/image: http://example.org/classics/tfa-book-cover.jpg
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
    op = parser()
    docheader, nodes = op.run(TFA_1, g)

    assert len(nodes) == 3


def test_parse_tfa_expanded():
    '''Test the expanded Things Fall Apart example with docheader'''
    from onya.graph import graph
    from onya.serial import literate_lex
    
    # Read the file
    with open('test/resource/schemaorg/thingsfallapart.onya') as f:
        content = f.read()
    
    # Create a graph and parse into it
    g = graph()
    doc_iri = literate_lex.parse(content, g)
    
    # Verify we got document metadata
    assert doc_iri == "http://example.org/classics/things-fall-apart"
    # Should have parsed multiple nodes
    assert len(g) > 0
    # Check that document node exists
    assert doc_iri in g
