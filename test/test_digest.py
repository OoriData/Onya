# -*- coding: utf-8 -*-
# test/test_digest.py
'''
The canonical content digest (`onya.digest`): equal across everything that doesn't change what a graph
says, different across anything that does.

    pytest -s test/test_digest.py
'''

import io

import pytest

from onya.digest import DEFAULT_EXCLUDE, digest, node_digests
from onya.graph import graph
from onya.serial.literate import LiterateParser, read, write

HEAD = '''# @docheader
* @document: http://e.o/doc{n}
* @nodebase: http://e.o/
* @schema: https://s.org/
'''

BODY = '''
# A [Person]
* name: Ada
* knows -> B
  * since: 1842
    * @as: integer
* email: a@e.o
* email: ada@e.o

# B [Person]
* name: Babbage
'''


def _g(text, n='', *, sources=False, g=None):
    g = graph() if g is None else g
    LiterateParser(document_source_assertions=sources).parse(HEAD.format(n=n) + text, g)
    return g


def _d(text, **kw):
    return digest(_g(text, **kw))


def test_shape_and_determinism():
    d = _d(BODY)
    assert d.startswith('sha256:') and len(d) == len('sha256:') + 64
    assert d == _d(BODY)


def test_one_file_versus_three():
    '''The motivating case: with document-source assertions, three documents are one KG.'''
    parts = BODY.split('\n# B')
    one = _g(BODY, sources=True)
    three = _g(parts[0], '1', sources=True)
    _g('\n# B' + parts[1], '2', sources=True, g=three)
    _g('\n# A\n* email: ada@e.o\n', '3', sources=True, g=three)  # even an overlapping repeat
    assert digest(one) == digest(three)
    # Teeth: left in, the bookkeeping makes them differ
    assert digest(one, exclude=()) != digest(three, exclude=())


def test_assertion_order_does_not_matter():
    shuffled = '''
# B [Person]
* name: Babbage

# A [Person]
* email: ada@e.o
* knows -> B
  * since: 1842
    * @as: integer
* email: a@e.o
* name: Ada
'''
    assert _d(BODY) == _d(shuffled)


def test_prefixes_and_nodebase_do_not_matter():
    g = _g(BODY)
    buf = io.StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://s.org/',
          prefixes={'x': 'http://other.example/'})
    plain = io.StringIO()
    write(g, plain)  # no namespace conventions at all: full IRIs everywhere
    assert digest(read(buf.getvalue()).graph) == digest(read(plain.getvalue()).graph) == digest(g)


def test_merged_and_unmerged_agree_and_digesting_changes_nothing():
    g = _g(BODY)
    _g(BODY, '2', g=g)  # the same content twice: duplicate occurrences, not merged
    before = sum(1 for _ in g._iter_assertions())
    d = digest(g)
    assert sum(1 for _ in g._iter_assertions()) == before  # `digest` did not merge the graph
    assert d == digest(g.copy().merge()) == _d(BODY)


def test_copy_has_the_same_digest():
    g = _g(BODY)
    assert digest(g.copy()) == digest(g)


@pytest.mark.parametrize('changed', [
    BODY.replace('name: Ada', 'name: Adah'),                  # a value
    BODY.replace('knows -> B', 'knows -> A'),                 # an edge target
    BODY.replace('# A [Person]', '# A [Person Mathematician]'),  # a type
    BODY.replace('* since: 1842', '* since: 1843'),           # a nested value
    BODY.replace('    * @as: integer', '    * @as: number'),   # an interpretation
    BODY.replace('    * @as: integer\n', ''),                 # ... or its absence
    BODY.replace('* knows -> B', '* knows -> B [=k1]'),       # an assertion @id
    BODY.replace('* name: Ada', '* name: Ada\n  * @ordering: 1'),  # an @ordering
    BODY.replace('* name: Ada\n', ''),                        # a missing assertion
])
def test_any_change_to_content_changes_the_digest(changed):
    assert _d(changed) != _d(BODY)


def test_fields_are_delimited():
    '''Teeth for the length prefixes: moving a character across a field boundary must change the digest.'''
    assert _d('\n# A\n* ab: c\n') != _d('\n# A\n* a: bc\n')


def test_different_ids_are_different_content():
    assert _d(BODY.replace('knows -> B', 'knows -> B [=k1]')) != _d(BODY.replace('knows -> B', 'knows -> B [=k2]'))


def test_interpretations_follow_the_merge_rules():
    plain, typed = '\n# A\n* n: 1\n', '\n# A\n* n: 1\n  * @as: integer\n'
    # One-sided adoption (SPEC Rule 2): an interpretation-free repeat merges into the typed one
    both = _g(plain)
    _g(typed, '2', g=both)
    assert digest(both) == _d(typed) != _d(plain)
    # Two different contracts stay two claims: not the same as either alone
    clash = _g(typed)
    _g(plain.replace('* n: 1\n', '* n: 1\n  * @as: number\n'), '2', g=clash)
    assert digest(clash) not in {_d(typed), _d(plain)}


def test_a_node_with_nothing_to_say_is_left_out():
    '''A node only referenced (a stub) and one declared empty are the same content as no node at all.'''
    stub = _g('\n# A\n* knows -> Ghost\n')
    declared = _g('\n# A\n* knows -> Ghost\n\n# Ghost\n')
    assert digest(stub) == digest(declared)
    assert 'http://e.o/Ghost' not in node_digests(declared)
    assert digest(declared) != digest(_g('\n# A\n* knows -> Other\n\n# Ghost\n'))


def test_node_digests_diff_two_versions():
    v1, v2 = _g(BODY), _g(BODY.replace('name: Babbage', 'name: Charles Babbage'))
    d1, d2 = node_digests(v1), node_digests(v2)
    assert d1.keys() == d2.keys() == {'http://e.o/A', 'http://e.o/B'}
    assert d1['http://e.o/A'] == d2['http://e.o/A'] and d1['http://e.o/B'] != d2['http://e.o/B']
    assert list(d1) == sorted(d1)


def test_a_subset_digest():
    g = _g(BODY)
    only_a = digest(g, nodes=['http://e.o/A'])
    assert only_a != digest(g) and only_a == digest(g, nodes=['A', 'http://e.o/A'][1:])
    changed_b = _g(BODY.replace('name: Babbage', 'name: Other'))
    assert digest(changed_b, nodes=['http://e.o/A']) == only_a  # B's change is not in A's digest
    assert digest(g, nodes=['http://e.o/A', 'http://e.o/B']) == digest(g)
    assert digest(g, nodes=['http://e.o/Nope']) == digest(graph())  # absent contributes nothing


def test_exclude_replaces_the_default_and_is_extendable():
    note = BODY + '\n# C\n* name: c\n  * internal: draft\n'
    g = _g(note, sources=True)
    without_note = digest(_g(BODY + '\n# C\n* name: c\n', sources=True))
    assert digest(g) != without_note
    assert digest(g, exclude=DEFAULT_EXCLUDE | {'https://s.org/internal'}) == without_note
    # A plain exclude= drops the defaults with it, so the source bookkeeping counts again
    assert digest(g, exclude={'https://s.org/internal'}) != without_note
    assert digest(g, exclude={'@source', '@Document', 'https://s.org/internal'}) == without_note  # `@` forms resolve


def test_an_excluded_type_drops_the_whole_node():
    g = _g(BODY + '\n# Scratch [Draft]\n* name: tmp\n')
    assert digest(g, exclude=DEFAULT_EXCLUDE | {'https://s.org/Draft'}) == _d(BODY)


def test_a_graph_with_clashing_ids_is_refused_not_hashed():
    from onya.graph import AssertionIdConflict
    g = _g('\n# A\n')  # the parser refuses a repeated id, so build the clash through the API
    for v in '12':
        g['http://e.o/A'].add_property('https://s.org/x', v).id = 'http://e.o/k'
    with pytest.raises(AssertionIdConflict):
        digest(g)
