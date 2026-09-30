# -*- coding: utf-8 -*-
# test/test_literate_long_text.py
'''
Markdown indented-text continuation for multi-line property values (SPEC § Long Text): lines
indented past a property's bullet continue its value, preserved exactly. `write(multiline='indent')`
emits the form, falling back to a `::` text reference where it can't read back exactly.

    pytest -s test/test_literate_long_text.py
'''

import io
import random

import pytest
from amara.iri import I

from onya.graph import graph
from onya.serial import literate
from onya.serial.literate import LiterateSyntaxError

from store.store_helpers import canon

H = '# @docheader\n* @nodebase: http://e.o/\n* @schema: https://schema.org/\n\n'
S = 'https://schema.org/'


def value(body, label='bio', node='A'):
    return literate.read(H + body).graph['http://e.o/' + node].any_prop_value(label)


def test_spec_example():
    doc = '''# A [Person]

* name: Chinua Achebe
* bio: Chinua Achebe (1930–2013) was a Nigerian writer considered a founder of modern African literature.

    Known for his novel Things Fall Apart and for writing about African life from an African perspective.

    After the Nigerian Civil War, he became an English professor in the United States.
* birthDate: 1930-11-16
'''
    assert value(doc) == ('Chinua Achebe (1930–2013) was a Nigerian writer considered a founder of modern '
                          'African literature.\n\nKnown for his novel Things Fall Apart and for writing about '
                          'African life from an African perspective.\n\nAfter the Nigerian Civil War, he '
                          'became an English professor in the United States.')
    assert value(doc, 'birthDate') == '1930-11-16'


@pytest.mark.parametrize('body,expected', [
    ('* bio: first\n  second\n  third\n', 'first\nsecond\nthird'),                 # 2 spaces, no blank line
    ('* bio: first\n\n    second\n', 'first\n\nsecond'),                          # 4 spaces, blank line first
    ('* bio: p1\n\n\n  p2\n\n  p3\n\n\n* x: y\n', 'p1\n\n\np2\n\np3'),            # blank runs kept; trailing dropped
    ('* bio: intro\n    quote:\n        deeper\n    back\n', 'intro\nquote:\n    deeper\nback'),  # relative indent
    ('* bio:\n    only the\n    paragraphs\n', 'only the\nparagraphs'),          # empty first line
    ('* bio: first\n    text\n    <!-- kept as text -->\n', 'first\ntext\n<!-- kept as text -->'),
    ('* bio: first\n    # not a header\n', 'first\n# not a header'),
    ('* bio: a *starred* word\n    *emphasis* is text\n', 'a *starred* word\n*emphasis* is text'),
])
def test_continuation_forms(body, expected):
    assert value('# A\n' + body) == expected


def test_directives_and_nested_assertions_follow_the_text():
    g = literate.read(H + '# A\n* bio: first [=bio-a] <!-- c -->\n    more\n  * @as: text\n  * note: n\n').graph
    bio = g.assertion_ids['http://e.o/bio-a']
    assert bio.value == 'first\nmore' and bio.interp == I('http://purl.org/onya/vocab/interp/text')
    assert bio.any_prop_value('note') == 'n'


def test_nested_properties_and_docheader_continue_too():
    g = literate.read(H + '# A\n* knows -> B\n  * note: n1\n      n2\n').graph
    assert next(g['http://e.o/A'].getedge('knows')).any_prop_value('note') == 'n1\nn2'
    r = literate.read('# @docheader\n* @document: http://e.o/d\n* @nodebase: http://e.o/\n'
                      '* abstract: A long\n    docheader value\n\n# A\n* name: A\n')
    assert any(p.value == 'A long\ndocheader value' for p in r.graph['http://e.o/d'].properties)


def test_same_graph_as_text_reference_form():
    indented = '# A\n* bio: first\n\n    second\n* name: A\n'
    textref = '# A\n* bio:: t\n* name: A\n\n:t = """first\n\nsecond"""\n'
    assert canon(literate.read(H + indented).graph) == canon(literate.read(H + textref).graph)


@pytest.mark.parametrize('body,needle', [
    ('* knows -> B\n    text\n', 'edge target'),
    ('* bio: "quoted"\n    text\n', 'quoted'),
    ('* bio: <http://e.o/x>\n    text\n', 'quoted (or `<IRI>`)'),
    ('* bio:: t\n    text\n', 'text reference'),
    ('* bio: first\n  * note: nested\n  stray\n', 'after a nested assertion'),
])
def test_continuation_errors(body, needle):
    with pytest.raises(LiterateSyntaxError) as e:
        literate.read(H + '# A\n' + body + '\n:t = """x"""\n')
    assert needle in str(e.value) and e.value.category == 'continuation'


def test_unindented_stray_text_keeps_its_diagnostic():
    with pytest.raises(LiterateSyntaxError) as e:
        literate.read(H + '# A\n* bio: first\nstray prose\n')
    assert e.value.category == 'unexpected'


def test_text_references_are_untouched():
    assert value('# A\n* bio:: t\n\n:t = """line one\n    indented two"""\n') == 'line one\n    indented two'


def _write(v, mode):
    g = graph()
    g.node(I('http://e.o/A')).add_property(I(S + 'description'), v)
    out = io.StringIO()
    literate.write(g, out, nodebase='http://e.o/', schema=S, multiline=mode)
    return out.getvalue()


def _reads_back(text, v):
    return literate.read(text).graph['http://e.o/A'].any_prop_value(S + 'description') == v


@pytest.mark.parametrize('v', ['first\nsecond', 'p1\n\n\np2', 'intro\n    indented\nback',
                               'q "quoted" ok\nmore', 'a\n  # heading-ish\nb', 'a\n:x = """not a ref'])
def test_write_indent_form(v):
    text = _write(v, 'indent')
    assert '::' not in text and _reads_back(text, v)


@pytest.mark.parametrize('v', ['x\n', ' lead\nb', 'a\n* bullet-ish', 'a\n   \nb', 'a\n  all\n  indented',
                               'ends [=x]\nmore', '\nleading newline', 'line1\n<!-- c -->\nline3'])
def test_write_indent_falls_back_to_text_reference(v):
    text = _write(v, 'indent')
    assert '::' in text and _reads_back(text, v)


def test_write_rejects_unknown_multiline_mode():
    with pytest.raises(ValueError, match='multiline'):
        _write('a\nb', 'fold')


def test_indent_mode_never_worse_than_text_reference():
    '''Seeded fuzz: wherever the default `::` form round-trips, `multiline='indent'` does too.'''
    random.seed(7)
    alphabet = ['a', 'b', ' ', '  ', '*', '* ', '#', ':', '"', "'", '<', '>', '<!--', '-->', '[=', ']', '\t', 'x y']
    for _ in range(600):
        v = '\n'.join(''.join(random.choice(alphabet) for _ in range(random.randint(0, 5)))
                      for _ in range(random.randint(2, 5)))
        try:
            textref_ok = _reads_back(_write(v, 'textref'), v)
        except Exception:
            textref_ok = False
        if textref_ok:
            assert _reads_back(_write(v, 'indent'), v), repr(v)
