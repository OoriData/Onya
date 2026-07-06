# -*- coding: utf-8 -*-
# test_assertion_id.py
'''
Tests for explicit assertion identifiers (the `@id` directive).

See SPEC.md § Assertion Identifiers.

    pytest -s test/test_assertion_id.py
'''

from io import StringIO

import pytest

from amara.iri import I

from onya import ONYA_BASEIRI
from onya.graph import graph
from onya.terms import ONYA_ASSERTION
from onya.serial.literate import AssertionIdConflict, LiterateParser, read, write


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''

FRIENDSHIP = DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * @id: chuks-ify-friendship
  * startDate: 2018-03-15

# ReviewNote

* disputes -> chuks-ify-friendship
  * source -> InterviewTranscript03
'''

FRIEND_ID = I('http://e.o/chuks-ify-friendship')


def _only(iterable):
    items = list(iterable)
    assert len(items) == 1, f'expected exactly one, got {len(items)}'
    return items[0]


def test_id_sets_assertion_id_and_registers():
    '''`@id` assigns the id to its assertion and registers it on the graph.'''
    g = graph()
    LiterateParser().parse(FRIENDSHIP, g)

    knows = _only(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    assert knows.id == FRIEND_ID
    assert g.assertion_ids[FRIEND_ID] is knows


def test_id_is_a_directive_not_a_property():
    '''`@id` must not create a property on the assertion (only startDate should remain).'''
    g = graph()
    LiterateParser().parse(FRIENDSHIP, g)

    knows = _only(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    labels = {str(p.label) for p in knows.properties}
    assert labels == {'https://schema.org/startDate'}
    assert str(ONYA_BASEIRI('id')) not in labels  # not stored under the onya @id vocab either


def test_identified_assertion_is_edge_target():
    '''An edge whose RHS names an assertion @id links to that assertion, not a fresh node.'''
    g = graph()
    LiterateParser().parse(FRIENDSHIP, g)

    knows = _only(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    disputes = _only(g['http://e.o/ReviewNote'].traverse('https://schema.org/disputes'))
    # The edge target is the identified assertion object itself
    assert disputes.target is knows
    # No placeholder node was minted for the assertion id
    assert FRIEND_ID not in g.nodes


def test_edge_target_forward_reference():
    '''Resolution works when the reference precedes the @id declaration in the document.'''
    reordered = DOCHEADER + '''
# ReviewNote

* disputes -> chuks-ify-friendship

# Chuks [Person]

* knows -> Ify
  * @id: chuks-ify-friendship
'''
    g = graph()
    LiterateParser().parse(reordered, g)

    knows = _only(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    disputes = _only(g['http://e.o/ReviewNote'].traverse('https://schema.org/disputes'))
    assert disputes.target is knows


def test_plain_node_target_still_creates_placeholder():
    '''Regression: an ordinary (non-@id) edge target still resolves/creates a node.'''
    g = graph()
    LiterateParser().parse(FRIENDSHIP, g)
    # Ify was never given its own block; it exists as an edge-target node
    assert I('http://e.o/Ify') in g.nodes


def test_assertion_carries_implicit_type():
    '''Every assertion has the implicit onya:Assertion type; nodes do not. This is what lets
    a match() consumer resolve an edge target and tell an assertion apart from a node.'''
    g = graph()
    LiterateParser().parse(FRIENDSHIP, g)

    knows = _only(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    assert ONYA_ASSERTION in knows.types
    assert ONYA_ASSERTION not in g['http://e.o/Ify'].types  # a node is not an assertion

    # Interpret a match() edge target: resolve via assertion_ids, then type-check
    review = g['http://e.o/ReviewNote']
    targets = [t for (_o, r, t, _a) in g.match(review.id) if str(r) == 'https://schema.org/disputes']
    assert targets == [FRIEND_ID]
    resolved = g.assertion_ids.get(targets[0])
    assert resolved is knows and ONYA_ASSERTION in resolved.types


def test_duplicate_assertion_id_conflicts():
    '''Two assertions declaring the same @id is a parse-time error.'''
    dup = DOCHEADER + '''
# A [Thing]

* p1: x
  * @id: shared
* p2: y
  * @id: shared
'''
    # The message should flag this as a parser-surface constraint, distinct from merge Rule 1
    with pytest.raises(AssertionIdConflict, match='parser-surface'):
        LiterateParser().parse(dup, graph())


def test_assertion_id_colliding_with_node_id_conflicts():
    '''An @id equal to a node id violates the shared identifier space.'''
    clash = DOCHEADER + '''
# foo [Thing]

* name: X

# B [Thing]

* rel -> Something
  * @id: foo
'''
    with pytest.raises(AssertionIdConflict):
        LiterateParser().parse(clash, graph())


ROUNDTRIP = DOCHEADER + '''
# Chuks [Person]

* knows -> Ify
  * @id: chuks-ify-friendship
  * startDate: 2018-03-15

# Ify [Person]

* name: Ify

# ReviewNote [Thing]

* disputes -> chuks-ify-friendship
'''


def test_id_roundtrips_through_write():
    '''write() emits `@id`, and re-reading restores the identifier and the link.

    Uses a fixture whose edge targets all have their own blocks, sidestepping a
    pre-existing write()/read() asymmetry where a target-only node emits an
    assertion-less block the grammar cannot re-parse.
    '''
    g = graph()
    LiterateParser().parse(ROUNDTRIP, g)

    buf = StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://schema.org/')
    serialized = buf.getvalue()
    assert '@id: chuks-ify-friendship' in serialized

    g2 = graph()
    read(serialized, g2)
    knows = _only(g2['http://e.o/Chuks'].traverse('https://schema.org/knows'))
    assert knows.id == FRIEND_ID
    disputes = _only(g2['http://e.o/ReviewNote'].traverse('https://schema.org/disputes'))
    assert disputes.target is knows
