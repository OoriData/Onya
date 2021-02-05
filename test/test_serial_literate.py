# -*- coding: utf-8 -*-
# test_serial_literate.py
'''
Test Onya literate serializer

pytest -s test/py/test_serial_literate.py
'''

# import functools

# Requires pytest-mock
import pytest

from amara3.iri import I

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
    nodes = op.run(TFA_1, g)

    assert len(nodes) == 3
