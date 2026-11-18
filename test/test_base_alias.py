# -*- coding: utf-8 -*-
# test/test_base_alias.py
'''`@base` (the old spelling of `@nodebase`) still works, but warns that it goes away in 0.8.0.'''

import warnings

import pytest

from onya.graph import graph
from onya.serial import literate

DOC = '''\
# @docheader

* @nodebase: http://e.o/
* @schema: http://s.o/

# a [T]

* name: x
'''


def _read(text):
    g = graph()
    literate.read(text, g)
    return g


def test_base_alias_warns_and_still_works():
    with pytest.warns(FutureWarning, match='0.8.0') as caught:
        g = _read(DOC.replace('@nodebase', '@base'))
    assert len(caught) == 1
    assert 'http://e.o/a' in {str(n) for n in g.nodes}  # same effect as @nodebase


def test_base_alias_in_iri_block_warns():
    text = DOC.replace('* @nodebase: http://e.o/\n', '* @iri:\n    * @base: http://e.o/\n')
    with pytest.warns(FutureWarning, match='@nodebase'):
        g = _read(text)
    assert 'http://e.o/a' in {str(n) for n in g.nodes}


def test_nodebase_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        _read(DOC)
