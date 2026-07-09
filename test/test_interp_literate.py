# -*- coding: utf-8 -*-
# test_interp_literate.py
'''
Tests for `@as` and `@interpretations` in Onya Literate: parsing records the contract as
an IRI on the assertion; it is never applied, and an unknown interpretation is never an
error. Round-trip preserves `interp` at every depth (see SPEC: @as).

Note on syntax: the `@interpretations` block header is written with a trailing colon
(`* @interpretations:`), consistent with the sibling `* @iri:` block.

    pytest -s test/test_interp_literate.py
'''

from io import StringIO

import pytest

from amara.iri import I

from onya.graph import graph
from onya.terms import ONYA_INTERP
from onya.serial.literate import LiterateParser, InterpretationParseError, read, write


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''

NUMBER = ONYA_INTERP('number')
DATETIME = ONYA_INTERP('datetime')
TEXT = ONYA_INTERP('text')


def _parse(*docs):
    g = graph()
    for d in docs:
        LiterateParser().parse(d, g)
    return g


def _one(iterable):
    items = list(iterable)
    assert len(items) == 1, f'expected exactly one, got {len(items)}'
    return items[0]


def _chuks(g):
    return g['http://e.o/Chuks']


# --- inline @as ---------------------------------------------------------------------

def test_as_sets_interp_and_creates_no_property():
    '''`@as` is a directive: it sets `interp` and adds no nested property.'''
    g = _parse(DOCHEADER + '''
# Chuks [Person]

* age: 28
  * @as: number
''')
    age = _one(_chuks(g).getprop('https://schema.org/age'))
    assert age.interp == NUMBER
    assert age.value == '28'
    assert list(age.properties) == []  # no nested property was created


def test_as_on_edge_warns_and_is_ignored():
    '''`@as` under an edge is ignored with a warning; parse still succeeds, interp stays None.'''
    text = DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * @as: number
'''
    g = graph()
    with pytest.warns(UserWarning, match='@as .* edge'):
        LiterateParser().parse(text, g)
    knows = _one(_chuks(g).traverse('https://schema.org/knows'))
    assert knows.interp is None


def test_duplicate_as_is_parse_error():
    '''A second `@as` on one property is a parse error.'''
    text = DOCHEADER + '''
# Chuks [Person]

* age: 28
  * @as: number
  * @as: datetime
'''
    with pytest.raises(InterpretationParseError, match='Duplicate @as'):
        LiterateParser().parse(text, graph())


def test_unknown_interp_iri_parses_clean():
    '''An interpretation the local software has never heard of is recorded, not rejected.'''
    text = DOCHEADER + '''
# Chuks [Person]

* riskScore: 0.87
  * @as: <http://fintech.example/interp/RiskScore>
'''
    g = _parse(text)
    score = _one(_chuks(g).getprop('https://schema.org/riskScore'))
    assert score.interp == I('http://fintech.example/interp/RiskScore')


def test_curie_interp_resolves_through_iri_prefixes():
    '''A CURIE interp name resolves through the document `@iri` prefixes.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @iri:
    * fin: http://fintech.example/interp/

# Chuks [Person]

* riskScore: 0.87
  * @as: fin:RiskScore
'''
    g = _parse(text)
    score = _one(_chuks(g).getprop('https://schema.org/riskScore'))
    assert score.interp == I('http://fintech.example/interp/RiskScore')


# --- docheader @interpretations defaults + precedence -------------------------------

def test_docheader_default_applies_at_node_level():
    '''A docheader default is desugared onto every matching property.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* age: 28
'''
    g = _parse(text)
    age = _one(_chuks(g).getprop('https://schema.org/age'))
    assert age.interp == NUMBER


def test_docheader_stanza_without_colon_is_rejected():
    '''The block header requires the trailing colon (like `@iri:`); the bare form fails.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations
    * age: number

# Chuks [Person]

* age: 28
'''
    with pytest.raises(Exception):  # grammar rejects a bare block header (no colon)
        LiterateParser().parse(text, graph())


def test_docheader_default_applies_nested_any_depth():
    '''The default matches by resolved label at any nesting depth, not just node level.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* knows -> Ify
  * meta: x
    * age: 5
'''
    g = _parse(text)
    knows = _one(_chuks(g).traverse('https://schema.org/knows'))
    meta = _one(knows.getprop('https://schema.org/meta'))
    nested_age = _one(meta.getprop('https://schema.org/age'))
    assert nested_age.interp == NUMBER


def test_inline_as_beats_docheader_default():
    '''Inline `@as` overrides the docheader default for that one property.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* age: 28
  * @as: text
'''
    g = _parse(text)
    age = _one(_chuks(g).getprop('https://schema.org/age'))
    assert age.interp == TEXT


def test_as_none_cancels_docheader_default():
    '''`@as: none` cancels the default: `interp` unset, as if never mentioned.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* age: 28
  * @as: none
'''
    g = _parse(text)
    age = _one(_chuks(g).getprop('https://schema.org/age'))
    assert age.interp is None


def test_duplicate_label_in_interpretations_stanza_is_error():
    '''A repeated label within the stanza is a parse error.'''
    text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number
    * age: datetime

# Chuks [Person]

* age: 28
'''
    with pytest.raises(InterpretationParseError, match='Duplicate label'):
        LiterateParser().parse(text, graph())


# --- merge across documents (behavioral example 3) ----------------------------------

def test_merge_across_docs_one_sided_adopts_then_conflict_stays_distinct():
    '''On an explicit merge: number + no-contract adopt number; a datetime doc stays distinct.

    Merge is on demand, so the founded assertions accumulate across parses and collapse
    only when `merge()` is called.
    '''
    doc_a = DOCHEADER + '''
# Acme [Organization]

* founded: 1999
  * @as: number
'''
    doc_c = DOCHEADER + '''
# Acme [Organization]

* founded: 1999
'''
    doc_b = DOCHEADER + '''
# Acme [Organization]

* founded: 1999
  * @as: datetime
'''
    g = _parse(doc_a, doc_c)
    assert len(list(g['http://e.o/Acme'].getprop('https://schema.org/founded'))) == 2  # not merged yet

    g.merge()  # one assertion, adopts number (one-sided adoption)
    founded = list(g['http://e.o/Acme'].getprop('https://schema.org/founded'))
    assert len(founded) == 1
    assert founded[0].interp == NUMBER

    LiterateParser().parse(doc_b, g)
    g.merge()  # datetime contract differs from number -> stays distinct (not an error)
    founded = list(g['http://e.o/Acme'].getprop('https://schema.org/founded'))
    assert len(founded) == 2
    assert {p.interp for p in founded} == {NUMBER, DATETIME}


# --- round-trip ---------------------------------------------------------------------

def _roundtrip(g):
    buf = StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://schema.org/')
    g2 = graph()
    read(buf.getvalue(), g2)
    return buf.getvalue(), g2


def test_reserved_names_roundtrip_as_bare_names():
    '''A Lightweight Types interp writes back as its reserved bare name and re-reads identically.'''
    g = _parse(DOCHEADER + '''
# Chuks [Person]

* age: 28
  * @as: number
* bio: hello
  * @as: text
''')
    serialized, g2 = _roundtrip(g)
    assert '@as: number' in serialized
    assert '@as: text' in serialized
    age = _one(g2['http://e.o/Chuks'].getprop('https://schema.org/age'))
    assert age.interp == NUMBER


def test_interp_roundtrips_on_nested_assertions():
    '''`interp` survives write -> read on nested assertions, not only at node level.'''
    g = _parse(DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * since: 1999
    * @as: number

# Ify [Person]

* name: Ify
''')
    serialized, g2 = _roundtrip(g)
    knows = _one(g2['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    since = _one(knows.getprop('https://schema.org/since'))
    assert since.interp == NUMBER


def test_interp_roundtrips_through_declared_abbreviation():
    '''An interp IRI in a declared prefix writes back as a CURIE and re-reads to the same IRI.'''
    g = _parse('''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @iri:
    * fin: http://fintech.example/interp/

# Chuks [Person]

* riskScore: 0.87
  * @as: fin:RiskScore
''')
    buf = StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://schema.org/',
          prefixes={'fin': 'http://fintech.example/interp/'})
    serialized = buf.getvalue()
    assert '@as: fin:RiskScore' in serialized  # rendered as the declared abbreviation

    g2 = graph()
    read(serialized, g2)
    score = _one(g2['http://e.o/Chuks'].getprop('https://schema.org/riskScore'))
    assert score.interp == I('http://fintech.example/interp/RiskScore')


def test_unknown_interp_iri_roundtrips_as_full_iri():
    '''An interp with no reserved name and no declared prefix writes back as a full IRI.'''
    g = _parse(DOCHEADER + '''
# Chuks [Person]

* riskScore: 0.87
  * @as: <http://fintech.example/interp/RiskScore>
''')
    serialized, g2 = _roundtrip(g)
    score = _one(g2['http://e.o/Chuks'].getprop('https://schema.org/riskScore'))
    assert score.interp == I('http://fintech.example/interp/RiskScore')
