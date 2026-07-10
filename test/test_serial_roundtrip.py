# -*- coding: utf-8 -*-
# test_serial_roundtrip.py
'''
Round-trip fidelity of the Onya Literate serializer for awkward string values — the
"string layer round-trips absolutely" invariant the persistence layer leans on.

    pytest -s test/test_serial_roundtrip.py
'''

import io

from onya.graph import graph
from onya.serial.literate import LiterateParser, write
from onya import LITERAL


DOC = 'http://e.o/doc'


def _roundtrip_value(value: str) -> str:
    '''Write a single property carrying `value`, re-parse, and return the recovered value.'''
    g = graph()
    n = g.node('http://e.o/N')
    n.add_property('http://s/p', value)
    out = io.StringIO()
    write(g, out, document=DOC)
    g2 = graph()
    LiterateParser().parse(out.getvalue(), g2)
    props = list(g2['http://e.o/N'].getprop('http://s/p'))
    assert len(props) == 1
    v = props[0].value
    return str(v) if isinstance(v, LITERAL) else v


def test_plain_value_roundtrips():
    assert _roundtrip_value('Chinua Achebe') == 'Chinua Achebe'


def test_value_with_embedded_double_quotes_roundtrips():
    assert _roundtrip_value('the "African Trilogy"') == 'the "African Trilogy"'


def test_value_with_backslash_roundtrips():
    assert _roundtrip_value(r'a\b\\c') == r'a\b\\c'


def test_value_with_colon_roundtrips():
    assert _roundtrip_value('ratio 3:1') == 'ratio 3:1'


def test_empty_value_roundtrips():
    assert _roundtrip_value('') == ''


def test_multiline_value_roundtrips_via_textref():
    text = 'First paragraph with a "quote".\n\nSecond paragraph, still going.'
    assert _roundtrip_value(text) == text


def test_textref_value_excludes_delimiters():
    '''A triple-quoted text reference stores its inner content, not the `"""` delimiters.'''
    src = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

# N [Thing]

* bio:: b

:b = """hello
world"""
'''
    g = graph()
    LiterateParser().parse(src, g)
    prop = next(g['http://e.o/N'].getprop('https://schema.org/bio'))
    assert str(prop.value) == 'hello\nworld'
