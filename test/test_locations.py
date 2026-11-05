# -*- coding: utf-8 -*-
# test/test_locations.py
'''
Source locations (#62): an opt-in side table saying which line of a document each node and
assertion came from, so diagnostics can name it. Off by default, when nothing is stored.

    pytest -s test/test_locations.py
'''

import pytest

from onya.graph import graph
from onya.interp import InterpretationError, validate, value_of
from onya.locations import Location
from onya.serial.literate import read, read_many
from onya.serial.literate import InterpretationParseError, LiterateSyntaxError
from onya.graph import AssertionIdConflict

HEAD = '''# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

'''
# line numbers below count from the top of HEAD (6 lines, so the first body line is 7)
BODY = '''# A [Person]

* name: Ada
* bio: first line
    continues here
    and here
* knows -> Typo
  * since: 1999

<!-- a comment -->

# B

* knows -> A
'''
TEXT = HEAD + BODY


def _a(g):
    return g['http://e.o/A']


def _by_label(container, label):
    (found,) = [a for a in (*container.properties, *container.edges) if str(a.label).endswith('/' + label)]
    return found


def test_off_by_default_costs_and_reports_nothing():
    g = graph()
    r = read(TEXT, g)
    assert r.locations is None and g._locations is None
    assert g.locate(_a(g)) is None


def test_nodes_and_assertions_are_located():
    g = graph()
    r = read(TEXT, g, track_locations=True)
    a = _a(g)
    assert g.locate(a) == Location('http://e.o/doc', 7, '# A [Person]')
    assert g.locate(_by_label(a, 'name')).lineno == 9
    assert g.locate(g['http://e.o/B']).lineno == 18
    assert g.locate(_by_label(g['http://e.o/B'], 'knows')).lineno == 20
    assert r.locations[a] == g.locate(a)


def test_continuation_lines_do_not_shift_later_lines():
    '''A multi-line value is located at its first line, and what follows keeps its true line number.'''
    g = graph()
    read(TEXT, g, track_locations=True)
    a = _a(g)
    bio = g.locate(_by_label(a, 'bio'))
    assert (bio.lineno, bio.line) == (10, '* bio: first line')
    assert g.locate(_by_label(a, 'knows')).lineno == 13  # it is on line 13, three lines after `bio`


def test_nested_assertions_are_located():
    g = graph()
    read(TEXT, g, track_locations=True)
    knows = _by_label(_a(g), 'knows')
    assert g.locate(_by_label(knows, 'since')).lineno == 14
    assert g.locate(_by_label(knows, 'since')).line == '  * since: 1999'


def test_tabs_and_text_refs_keep_line_numbers():
    g = graph()
    read(HEAD + '# A\n\n* knows -> B\n\t* since: 1999\n* note:: n\n* name: X\n\n:n = """long\ntext"""\n', g,
         track_locations=True)
    a = _a(g)
    assert g.locate(_by_label(_by_label(a, 'knows'), 'since')).lineno == 10
    assert g.locate(_by_label(a, 'note')).lineno == 11
    assert g.locate(_by_label(a, 'name')).lineno == 12


def test_node_with_several_blocks_is_located_at_the_first():
    g = graph()
    read(HEAD + '# A\n\n* name: one\n\n# A\n\n* name: two\n', g, track_locations=True)
    assert g.locate(_a(g)).lineno == 7


def test_equal_assertions_have_separate_locations():
    '''Keyed by object, not value: two identical lines are two assertions on two lines.'''
    g = graph()
    read(HEAD + '# A\n\n* name: same\n* name: same\n', g, track_locations=True)
    props = sorted(_a(g).properties, key=lambda p: g.locate(p).lineno)
    assert [g.locate(p).lineno for p in props] == [9, 10]


def test_reads_accumulate_on_the_graph_and_results_are_per_read():
    g = graph()
    r1 = read(HEAD + '# A\n\n* name: Ada\n', g, track_locations=True)
    r2 = read(HEAD + '# B\n\n* name: Bo\n', g, track_locations=True)
    assert len(r1.locations) == 2 and len(r2.locations) == 2  # node + property each
    assert g.locate(g['http://e.o/A']) is not None and g.locate(g['http://e.o/B']) is not None


def test_union_carries_locations_and_copy_does_not():
    a, b = graph(), graph()
    read(HEAD + '# A\n\n* name: Ada\n', a, track_locations=True)
    read(HEAD + '# B\n\n* name: Bo\n', b, track_locations=True)
    nb = b['http://e.o/B']
    a.union(b)
    assert a.locate(nb).lineno == 7  # adopted by identity
    assert a.copy().locate(a['http://e.o/A']) is None  # new objects: nothing to say about where they were written


def test_read_many_names_the_file(tmp_path):
    (tmp_path / 'a.onya').write_text(HEAD + '# A\n\n* knows -> Typo\n')
    (tmp_path / 'b.onya').write_text(HEAD + '\n\n# B\n\n* knows -> Nowhere\n')
    res = read_many(str(tmp_path), track_locations=True)
    where = {str(d.target).rsplit('/', 1)[1]: d.location for d in res.dangling}
    assert (where['Typo'].lineno, where['Typo'].source.endswith('a.onya')) == (9, True)
    assert (where['Nowhere'].lineno, where['Nowhere'].source.endswith('b.onya')) == (11, True)
    assert len(res.locations) == sum(len(r.locations) for r in res.results.values())
    assert read_many(str(tmp_path)).locations is None


def test_dangling_names_its_line():
    r = read(TEXT, graph(), track_locations=True)
    (d,) = r.dangling
    assert d.lineno == 13 and d.location.line == '* knows -> Typo'
    assert str(d).endswith('(at http://e.o/doc:13)')
    assert read(TEXT, graph()).dangling[0].lineno is None


def test_dangling_error_names_the_line():
    from onya.serial.literate import DanglingTargetError
    with pytest.raises(DanglingTargetError, match=r'doc:13'):
        read(TEXT, graph(), track_locations=True, on_dangling='error')


BAD_AGE = HEAD + '# A\n\n* age: old\n  * @as: number\n'


def test_finding_and_report_carry_the_location():
    g = graph()
    read(BAD_AGE, g, track_locations=True)
    (f,) = validate(g).findings
    assert f.location.lineno == 9
    assert 'doc:9' in str(validate(g))
    untracked = graph()
    read(BAD_AGE, untracked)
    assert validate(untracked).findings[0].location is None
    assert '(location not tracked)' in str(validate(untracked))


def test_interpretation_error_names_the_line_when_it_can():
    g = graph()
    read(BAD_AGE, g, track_locations=True)
    (age,) = _a(g).properties
    with pytest.raises(InterpretationError) as ei:
        value_of(age)
    assert ei.value.location.lineno == 9 and str(ei.value).endswith('(at http://e.o/doc:9)')
    g2 = graph()
    read(BAD_AGE, g2)
    (age2,) = _a(g2).properties
    with pytest.raises(InterpretationError) as ei:
        value_of(age2)
    assert ei.value.location is None and 'at http' not in str(ei.value)  # nothing to add, nothing said


def test_parse_errors_name_the_line():
    with pytest.raises(InterpretationParseError, match=r'\(line 14\)'):
        read(HEAD + '# A\n\n* age: 1\n  * @as: number\n\n* x: 1\n  * @as: number\n  * @as: text\n', graph())
    with pytest.raises(AssertionIdConflict, match=r'\(line 13\)'):
        read(HEAD + '# A\n\n* x: 1\n  * @id: dup\n\n* y: 2\n  * @id: dup\n', graph())
    with pytest.raises(LiterateSyntaxError, match=r'\(line 9\)') as ei:
        read(HEAD + '# A\n* x: 1 [=a]\n  * @id: b\n', graph())
    assert ei.value.lineno == 9
