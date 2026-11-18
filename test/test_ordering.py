# -*- coding: utf-8 -*-
# test/test_ordering.py
'''
The ordering layer (`onya.ordering`): the docheader `@ordered` stanza stamps `@ordering` from document
order, `ordered_values()` / `ordered_targets()` read it back strictly, union stays generic, `resolve()`
is the explicit fixup, and write/read round-trips order.

    pytest -s test/test_ordering.py
'''

import io
import warnings

import pytest
from amara.iri import I

from onya import view
from onya.graph import graph
from onya.ordering import OrderingConflict, OrderingError, resolve, stamp_of
from onya.serial.literate import read, write
from onya.terms import ONYA, ONYA_ORDERING, unknown_reserved_terms

HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://s.org/
'''
ORDERED = HEAD + '* @ordered: sourceField author\n'
A = 'http://e.o/A'

FIELDS = '''
# A [Mapping]
* sourceField: addr2
* sourceField: addr1
* sourceField: city
* name: x
'''


def _read(text, g=None):
    g = graph() if g is None else g
    return read(text, g), g


def _stamps(node, label):
    '''{value: stamp strings} for a node's properties under `label`'''
    return {p.value: sorted(s.value for s in p.properties if s.label == ONYA_ORDERING)
            for p in node.getprop(label)}


def _roundtrip(g, **kw):
    buf = io.StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://s.org/', **kw)
    g2 = graph()
    r = read(buf.getvalue(), g2)
    return buf.getvalue(), g2, r


# --- stamping --------------------------------------------------------------------------

def test_stanza_stamps_document_order_on_properties_and_edges():
    r, g = _read(ORDERED + FIELDS + '* author -> bob\n* author -> al\n')
    n = g[A]
    assert n.ordered_values('sourceField') == ['addr2', 'addr1', 'city']  # document order, not sorted
    assert [t.id for t in n.ordered_targets('author')] == ['http://e.o/bob', 'http://e.o/al']
    assert _stamps(n, 'sourceField') == {'addr2': ['1'], 'addr1': ['2'], 'city': ['3']}
    assert r.ordered == {I('https://s.org/sourceField'), I('https://s.org/author')}


def test_undeclared_labels_are_untouched():
    _, g = _read(HEAD + FIELDS)
    assert _stamps(g[A], 'sourceField') == {'addr2': [], 'addr1': [], 'city': []}  # no stamps appear
    assert g[A].values('sourceField') == ['addr1', 'addr2', 'city']  # sets, sorted, as always
    with pytest.raises(OrderingError, match='no @ordering'):
        g[A].ordered_values('sourceField')


def test_only_declared_labels_are_stamped():
    _, g = _read(HEAD + '* @ordered: sourceField\n' + FIELDS)
    assert not any(p.properties for p in g[A].getprop('name'))


def test_a_hand_written_stamp_wins_and_gaps_are_fine():
    _, g = _read(HEAD + FIELDS + '''
# B
* sourceField: late
  * @ordering: 30
* sourceField: early
  * @ordering: 10
* sourceField: mid
  * @ordering: 20
''')
    assert g['http://e.o/B'].ordered_values('sourceField') == ['early', 'mid', 'late']  # no stanza needed


def test_the_stanza_does_not_overwrite_a_hand_stamp():
    _, g = _read(ORDERED + '''
# A
* sourceField: a
* sourceField: b
  * @ordering: 10
* sourceField: c
''')
    assert _stamps(g[A], 'sourceField') == {'a': ['1'], 'b': ['10'], 'c': ['3']}
    assert g[A].ordered_values('sourceField') == ['a', 'c', 'b']


def test_stamps_are_compared_as_integers_not_text():
    _, g = _read(HEAD + '''
# A
* v: ten
  * @ordering: 10
* v: nine
  * @ordering: 9
* v: sep
  * @ordering: 1_000
* v: padded
  * @ordering: 007
''')
    assert g[A].ordered_values('v') == ['padded', 'nine', 'ten', 'sep']


def test_numbering_continues_across_blocks_of_one_document():
    _, g = _read(ORDERED + '''
# A
* sourceField: a

# B
* sourceField: other

# A
* sourceField: b
''')
    assert g[A].ordered_values('sourceField') == ['a', 'b']  # not two stamps of 1
    assert g['http://e.o/B'].ordered_values('sourceField') == ['other']  # numbered per node


def test_nested_assertions_are_numbered_under_their_own_parent():
    _, g = _read(HEAD + '* @ordered: step\n' + '''
# A
* name: x
  * step: one
  * step: two
* title: y
  * step: uno
''')
    name = next(iter(g[A].getprop('name')))
    assert [p.value for p in sorted(name.getprop('https://s.org/step'), key=stamp_of)] == ['one', 'two']
    title = next(iter(g[A].getprop('title')))
    assert [stamp_of(p) for p in title.getprop('https://s.org/step')] == [1]  # its own parent, its own count


def test_a_label_may_be_a_curie_or_a_full_iri_in_the_stanza():
    _, g = _read('''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://s.org/
* @iri:
    * ex: http://x.example/
* @ordered: ex:rank <http://y.example/pos>

# A
* ex:rank: a
* ex:rank: b
* <http://y.example/pos>: p
* <http://y.example/pos>: q
''')
    assert g[A].ordered_values('ex:rank') == ['a', 'b']
    assert g[A].ordered_values('http://y.example/pos') == ['p', 'q']


def test_repeated_stanza_lines_accumulate():
    _, g = _read(HEAD + '* @ordered: one\n* @ordered: two\n# A\n* one: a\n* two: b\n')
    assert g[A].ordered_values('one') == ['a'] and g[A].ordered_values('two') == ['b']


def test_stamps_carry_no_interpretation():
    '''Stamps are plain strings: reading them as integers is the accessor's job (no `@as` noise).'''
    _, g = _read(ORDERED + FIELDS)
    assert all(s.interp is None for p in g[A].getprop('sourceField') for s in p.properties)


# --- the duplicate-claim warning (a known limitation) ----------------------------------

def test_repeating_a_claim_under_an_ordered_label_warns():
    text = ORDERED + '\n# A\n* sourceField: x\n* sourceField: y\n* sourceField: x\n'
    with pytest.warns(UserWarning, match='appears twice.*only one position survives'):
        _read(text)


def test_repeating_an_edge_target_warns_too():
    with pytest.warns(UserWarning, match='author.*appears twice'):
        _read(ORDERED + '\n# A\n* author -> bob\n* author -> bob\n')


def test_the_same_value_under_an_unordered_label_stays_silent():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        _read(HEAD + '\n# A\n* v: x\n* v: x\n')


def test_an_id_per_occurrence_keeps_both_repeats():
    '''The remedy the warning names: `[=name]` gives each occurrence its own assertion, and its own place.'''
    text = ORDERED + '\n# A\n* sourceField: x [=r1]\n* sourceField: y\n* sourceField: x [=r3]\n'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        _, g = _read(text)
    g.merge()
    assert g[A].ordered_values('sourceField') == ['x', 'y', 'x']


# --- strictness ------------------------------------------------------------------------

def test_a_missing_stamp_is_an_error_not_set_order():
    _, g = _read(HEAD + '\n# A\n* v: a\n  * @ordering: 1\n* v: b\n')
    with pytest.raises(OrderingError, match="'b' has no @ordering"):
        g[A].ordered_values('v')


def test_a_non_integer_stamp_is_an_error():
    _, g = _read(HEAD + '\n# A\n* v: a\n  * @ordering: first\n')
    with pytest.raises(OrderingError, match='not an integer'):
        g[A].ordered_values('v')
    _, g = _read(HEAD + '\n# A\n* v: a\n  * @ordering: 1.0\n')
    with pytest.raises(OrderingError, match='not an integer'):
        g[A].ordered_values('v')


def test_no_values_is_an_empty_list():
    _, g = _read(HEAD + '\n# A\n* v: a\n')
    assert g[A].ordered_values('nothing') == [] and g[A].ordered_targets('nothing') == []


def test_two_claims_sharing_a_position_conflict():
    _, g = _read(HEAD + '\n# A\n* v: a\n  * @ordering: 1\n* v: b\n  * @ordering: 1\n')
    with pytest.raises(OrderingConflict, match='share @ordering 1'):
        g[A].ordered_values('v')


def test_union_leaves_two_stamps_and_the_accessor_names_the_conflict():
    '''Union stays generic: same claim, two stamps (the T8 example); it is the accessor that objects.'''
    text_a = HEAD + '\n# A\n* v: city\n  * @ordering: 3\n'
    text_b = HEAD + '\n# A\n* v: city\n  * @ordering: 5\n'
    _, g = _read(text_a)
    read(text_b, g)
    g.merge()  # same skeleton: one assertion, two stamps; merge itself is not asked to judge
    (p,) = g[A].getprop('v')
    assert sorted(s.value for s in p.properties) == ['3', '5']
    with pytest.raises(OrderingConflict, match=r"conflicting @ordering values \[3, 5\]") as e:
        g[A].ordered_values('v')
    assert e.value.label == 'https://s.org/v' and e.value.origin is g[A]


def test_the_same_claim_with_the_same_stamp_counts_once():
    text = HEAD + '\n# A\n* v: a\n  * @ordering: 1\n'
    _, g = _read(text)
    read(text, g)  # not merged: two identical occurrences
    assert g[A].ordered_values('v') == ['a']


def test_accessors_take_the_same_label_forms_as_getprop():
    _, g = _read(ORDERED + FIELDS)
    n = g[A]
    forms = ['sourceField', 'https://s.org/sourceField', 'schema:sourceField']
    assert all(n.ordered_values(f) == ['addr2', 'addr1', 'city'] for f in forms)


# --- resolve ---------------------------------------------------------------------------

def _conflicted():
    _, g = _read(HEAD + '\n# A\n* v: city\n  * @ordering: 3\n* v: zip\n  * @ordering: 4\n')
    read(HEAD + '\n# A\n* v: city\n  * @ordering: 9\n', g)
    g.merge()
    return g


@pytest.mark.parametrize('policy, expected', [('first', ['city', 'zip']), ('last', ['zip', 'city'])])
def test_resolve_first_and_last(policy, expected):
    g = _conflicted()
    with pytest.raises(OrderingConflict):
        g[A].ordered_values('v')
    assert resolve(g, policy) == 1  # one claim was changed
    assert g[A].ordered_values('v') == expected
    assert resolve(g, policy) == 0  # nothing left to settle


def test_resolve_takes_a_callable():
    g = _conflicted()
    seen = []

    def middle(assertion, nums):
        seen.append((assertion.value, nums))
        return 4  # tie with zip's: `resolve` settles stamps, it doesn't judge the result
    resolve(g, middle)
    assert seen == [('city', [3, 9])]
    with pytest.raises(OrderingConflict, match='share'):
        g[A].ordered_values('v')


def test_resolve_leaves_unparseable_stamps_and_rejects_a_bad_policy():
    _, g = _read(HEAD + '\n# A\n* v: a\n  * @ordering: 1\n  * @ordering: x\n')
    assert resolve(g) == 0
    with pytest.raises(ValueError, match='policy'):
        resolve(g, 'median')


# --- write / read ----------------------------------------------------------------------

def test_plain_write_keeps_stamps_and_order():
    r, g = _read(ORDERED + FIELDS + '* author -> bob\n* author -> al\n')
    text, g2, _ = _roundtrip(g)
    assert '* @ordering: 1' in text and '@ordered' not in text  # faithful and explicit
    assert g2[A].ordered_values('sourceField') == ['addr2', 'addr1', 'city']
    assert [t.id for t in g2[A].ordered_targets('author')] == ['http://e.o/bob', 'http://e.o/al']
    assert text.index('addr2') < text.index('addr1') < text.index('city')  # written in order, too


def test_write_with_ordered_hands_back_the_stanza_and_elides_stamps():
    r, g = _read(ORDERED + FIELDS + '* author -> bob\n* author -> al\n')
    text, g2, r2 = _roundtrip(g, ordered=r.ordered)
    assert '@ordered: ' in text and '@ordering' not in text  # stanza instead of stamps
    assert text.index('addr2') < text.index('addr1') < text.index('city')
    assert g2[A].ordered_values('sourceField') == ['addr2', 'addr1', 'city']
    assert [t.id for t in g2[A].ordered_targets('author')] == ['http://e.o/bob', 'http://e.o/al']
    assert r2.ordered == r.ordered  # and the next read hands it on again


def test_stamps_that_are_not_exactly_1_to_n_are_written_out_even_under_the_stanza():
    r, g = _read(ORDERED + '\n# A\n* sourceField: a\n  * @ordering: 10\n* sourceField: b\n  * @ordering: 20\n')
    text, g2, _ = _roundtrip(g, ordered=r.ordered)
    assert '@ordering: 10' in text and '@ordering: 20' in text
    assert g2[A].ordered_values('sourceField') == ['a', 'b']


def test_a_stamp_that_says_more_than_its_number_is_never_dropped():
    r, g = _read(ORDERED + '\n# A\n* sourceField: a\n  * @ordering: 1\n    * @source: hand\n')
    text, g2, _ = _roundtrip(g, ordered=r.ordered)
    assert '@ordering: 1' in text and '@source: hand' in text
    (p,) = g2[A].getprop('sourceField')
    assert [s.value for s in p.getprop(ONYA('source'))] == []  # nested under the stamp, not under `a`
    (s,) = p.getprop(ONYA_ORDERING)
    assert [x.value for x in s.getprop(ONYA('source'))] == ['hand']


def test_labels_outside_the_stanza_keep_their_stamps():
    r, g = _read(HEAD + '* @ordered: sourceField\n' + FIELDS + '* other: a\n  * @ordering: 1\n')
    text, g2, _ = _roundtrip(g, ordered=r.ordered)
    assert text.count('@ordering') == 1  # `other` is not in the stanza, so its stamp stays explicit
    assert g2[A].ordered_values('other') == ['a']


def test_write_ordered_accepts_plain_iri_strings():
    _, g = _read(ORDERED + FIELDS)
    text, g2, _ = _roundtrip(g, ordered=['https://s.org/sourceField'])
    assert g2[A].ordered_values('sourceField') == ['addr2', 'addr1', 'city']
    assert text.count('@ordering') == 0


def test_writing_the_re_read_graph_gives_the_same_text():
    '''read(write(g)) is stable: writing the re-read graph gives the same text.'''
    r, g = _read(ORDERED + FIELDS)
    t1, g2, r2 = _roundtrip(g, ordered=r.ordered)
    buf = io.StringIO()
    write(g2, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='https://s.org/', ordered=r2.ordered)
    assert buf.getvalue() == t1


# --- vocabulary ------------------------------------------------------------------------

def test_ordering_terms_are_reserved_by_their_layer():
    from onya.terms import RESERVED
    assert RESERVED['ordering'] == RESERVED['ordered'] == 'ordering'
    _, g = _read(ORDERED + FIELDS)
    assert unknown_reserved_terms(g) == {}  # `@ordering` stamps are not flagged as typos


# --- views -----------------------------------------------------------------------------

VIEW_DOC = HEAD + '* @ordered: sourceField\n' + '''
# A [Mapping]
* sourceField: zed
* sourceField: alpha
* sourceField: mid
* partial: z
  * @ordering: 1
* partial: a
'''


def _fields(g, *fields):
    out = view.project(g, A, {'type': 'Mapping', 'fields': list(fields)})
    return dict(out['fields'])


def test_a_many_field_over_an_ordered_label_follows_the_stamps():
    _, g = _read(VIEW_DOC)
    f = _fields(g, {'label': 'sourceField', 'many': True})
    assert f['sourceField'] == ['zed', 'alpha', 'mid']  # not alphabetical
    assert _fields(g, 'sourceField')['sourceField'] == 'zed'  # and a single-valued field shows the first


def test_a_half_stamped_label_is_an_ordinary_label():
    _, g = _read(VIEW_DOC)
    assert _fields(g, {'label': 'partial', 'many': True})['partial'] == ['a', 'z']  # sorted, as before


def test_order_by_ordering_just_works():
    _, g = _read(VIEW_DOC)
    g[A].add_property('rank', 'x')  # a label with no stamps at all: unaffected
    f = _fields(g, {'label': 'sourceField', 'many': True, 'order_by': '@ordering'})
    assert f['sourceField'] == ['zed', 'alpha', 'mid']
    desc = _fields(g, {'label': 'sourceField', 'many': True, 'order_by': '-@ordering'})
    assert desc['sourceField'] == ['mid', 'alpha', 'zed']


def test_order_by_ordering_compares_numbers_not_text():
    _, g = _read(HEAD + '\n# A [Mapping]\n* v: ten\n  * @ordering: 10\n* v: nine\n  * @ordering: 9\n')
    assert _fields(g, {'label': 'v', 'many': True, 'order_by': '@ordering'})['v'] == ['nine', 'ten']
