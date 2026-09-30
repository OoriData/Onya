# -*- coding: utf-8 -*-
# test/test_literate_roundtrip_strings.py
'''
`read(write(g))` reproduces every string value exactly, in every `multiline` mode (#50): tabs,
quotes, `"""`, backslashes, comment markers, bullet- and header-like lines, blank runs, control
characters. And a tab in a hand-written value is kept, while leading tabs are Markdown indentation.

    pytest -s test/test_literate_roundtrip_strings.py
'''

import io

import pytest
from amara.iri import I
from hypothesis import given, settings, strategies as st

from onya.graph import graph
from onya.serial import literate

S = 'https://schema.org/'
H = '# @docheader\n* @nodebase: http://e.o/\n\n'

# Adversarial fragments mixed with arbitrary text, so structure-like lines come up often.
FRAGMENTS = st.sampled_from(['"', "'", '"""', '\\', '\\n', '\t', '\r', '\n', '\n\n', ' ', '  ', '* ', '#',
                             ':', '<', '>', '<!--', '-->', '[=x]', '::', '->', ' [=a-b]', '\x0b', '\x0c'])
VALUES = st.lists(st.one_of(FRAGMENTS, st.text(max_size=6)), max_size=12).map(''.join)


def roundtrip(v: str, mode: str, nested: bool = False):
    g = graph()
    a = g.node(I('http://e.o/A'))
    if nested:
        e = a.add_edge(I(S + 'knows'), g.node(I('http://e.o/B')))
        e.add_property(I(S + 'd'), v)
    else:
        a.add_property(I(S + 'd'), v)
    out = io.StringIO()
    literate.write(g, out, nodebase='http://e.o/', schema=S, multiline=mode)
    text = out.getvalue()
    back = literate.read(text).graph['http://e.o/A']
    got = next(back.getedge(I(S + 'knows'))).any_prop_value(I(S + 'd')) if nested else back.any_prop_value(I(S + 'd'))
    return got, text


@pytest.mark.filterwarnings('ignore:Onya Literate. node block')  # the bare edge target in `nested`
@settings(max_examples=400, deadline=None)
@given(v=VALUES, mode=st.sampled_from(['textref', 'indent']), nested=st.booleans())
def test_any_string_round_trips(v, mode, nested):
    got, text = roundtrip(v, mode, nested)
    assert got == v
    assert '\t' not in text   # write() never emits a literal tab


@pytest.mark.parametrize('v', [
    'col1\tcol2\tcol3',
    'Asked about the sequel, she said:\n"Not yet."',
    'Usage:\n    def f():\n        """Docstring."""',
    'He wrote "x"\nand "y"',
    'Tabs\n\tindented with a tab',
    "'starts with a single quote",
    '<angle-bracketed, not an IRI>',
    'a literal backslash-n: \\n',
    'crlf\r\nline',
    '><!---->',                        # found by hypothesis: an unquoted comment would be stripped
])
@pytest.mark.parametrize('mode', ['textref', 'indent'])
def test_ticket_examples(v, mode):
    assert roundtrip(v, mode)[0] == v


def value(body, label='d'):
    return literate.read(H + body).graph['http://e.o/A'].any_prop_value(label)


@pytest.mark.parametrize('body,expected', [
    ('# A\n* d: "x\ty"\n', 'x\ty'),                                   # hand-written quoted tab
    ('# A\n* d: col1\tcol2\n', 'col1\tcol2'),                          # unquoted
    ('# A\n* d:: t\n\n:t = """Tabs\n\tindented"""\n', 'Tabs\n\tindented'),   # text-ref body: literal
    ('# A\n* d: first\n\tsecond\tmid\n', 'first\nsecond\tmid'),        # continuation: leading tab is indent
])
def test_hand_written_tabs(body, expected):
    assert value(body) == expected


def test_leading_tabs_are_markdown_indentation():
    g = literate.read(H + '# A\n* d: top\n\t* note: nested\n\t\t* deeper: yes\n').graph
    note = next(next(g['http://e.o/A'].getprop('d')).getprop('note'))
    assert note.value == 'nested' and note.any_prop_value('deeper') == 'yes'


def test_tab_counts_to_four_columns():
    # A tab and 4 spaces are the same depth (siblings under `d`), as in Markdown. Under the old
    # 8-column expansion the tab-indented bullet was deeper, nesting under `a`.
    g = literate.read(H + '# A\n* d: top\n    * a: 1\n\t* b: 2\n').graph
    d = next(g['http://e.o/A'].getprop('d'))
    assert {p.value for p in d.properties} == {'1', '2'}
