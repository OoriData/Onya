# -*- coding: utf-8 -*-
# test/test_literate_comments.py
'''
HTML comments never reach the graph (SPEC: Comments): trailing comments on unquoted values and
on node headers are dropped, and diagnostics never mistake a comment's `-->` for an edge arrow.

    pytest -s test/test_literate_comments.py
'''

import pytest

from onya.serial import literate
from onya.serial.literate import EdgeArrowError, LiterateSyntaxError

H = '# @docheader\n* @nodebase: http://e.o/\n* @schema: https://schema.org/\n\n'
A = 'http://e.o/A'


def parse(body, **kw):
    return literate.read(H + body, **kw).graph


def test_trailing_comments_on_unquoted_values_are_dropped():
    g = parse('# A\n* name: X     <!-- c -->\n* two: Y <!-- a --> <!-- b -->\n* knows -> B <!-- c -->\n')
    a = g[A]
    assert a.any_prop_value('name') == 'X' and a.any_prop_value('two') == 'Y'
    assert a.any_edge_target('knows').id == 'http://e.o/B'


def test_comment_after_inline_id():
    g = parse('# A\n* knows -> B [=a-b] <!-- c -->\n')
    assert 'http://e.o/a-b' in g.assertion_ids


def test_quoted_and_mid_value_comment_text_is_kept():
    g = parse('# A\n* q: "Z <!-- literal -->"\n* mid: before <!-- x --> after\n')
    assert g[A].any_prop_value('q') == 'Z <!-- literal -->'           # quoted: it's the value
    assert g[A].any_prop_value('mid') == 'before <!-- x --> after'    # only *trailing* comments go


@pytest.mark.parametrize('header', ['# A [Person]     <!-- c -->', '# A     <!-- c -->',
                                    '# A [Person] <!-- a --> <!-- b -->'])
def test_node_header_comments(header):
    g = parse(f'{header}\n* name: X\n')
    assert g[A].any_prop_value('name') == 'X'
    assert ('[Person]' in header) == ('https://schema.org/Person' in {str(t) for t in g[A].types})


def test_header_comment_does_not_swallow_next_line():
    g = parse('# A [Person] <!-- c -->\n<!-- a comment line -->\n* name: X\n')
    assert g[A].any_prop_value('name') == 'X'


def test_comment_close_is_not_a_stray_arrow():
    # The real problem is the missing `:`; the comment's `-->` must not be blamed.
    with pytest.raises(LiterateSyntaxError) as e:
        parse('# A\n* name: A\n* temperature "25"   <!-- qualified value -->\n')
    assert e.value.category == 'assertion' and 'missing `:`' in str(e.value)


def test_blank_lines_between_assertions():
    g = parse('# A\n* name: A\n  * note: on the name\n\n* temperature: "25"  <!-- c -->\n\n\n* unit: C\n')
    a = g[A]
    assert {a.any_prop_value(k) for k in ('name', 'temperature', 'unit')} == {'A', '25', 'C'}
    assert next(a.getprop('name')).any_prop_value('note') == 'on the name'


def test_real_stray_arrow_still_caught_and_comment_left_intact():
    with pytest.raises(EdgeArrowError, match=r'\* knows -> B <!-- note -->'):
        parse('# A\n* knows => B <!-- note -->\n')
    with pytest.warns(UserWarning, match='fat arrow'):
        g = parse('# A\n* knows => B <!-- note -->\n', lenient_arrows=True)
    assert g[A].any_edge_target('knows').id == 'http://e.o/B'


def test_blank_line_under_docheader_continues_it():
    r = literate.read('# @docheader\n* @document: http://e.o/doc\n* @nodebase: http://e.o/\n\n'
                      '* about: after a blank line\n\n# A\n* name: A\n')
    assert r.graph['http://e.o/doc'].any_prop_value('http://e.o/about') is None  # no @schema: bare label
    assert any(p.value == 'after a blank line' for p in r.graph['http://e.o/doc'].properties)
