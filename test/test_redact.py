# -*- coding: utf-8 -*-
# test/test_redact.py
'''`@sensitivity` on a `@Property`, `onya.redact.redact`, and the `@transient` do-not-persist marker (#84).'''

import io

import pytest

from onya.graph import graph
from onya.redact import redact
from onya.serial.literate import read, write
from onya.shape import load_shapes, validate
from onya.transient import TransientError, check_persistable, mark, transient

SRC = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# Person [@Class]
# name [@Property]
* @appliesTo -> Person
# salary [@Property]
* @appliesTo -> Person
* @sensitivity: partner
# diagnosis [@Property]
* @sensitivity: clinical
# manager [@Property]
* @range -> Person
* @sensitivity: partner

# ada [Person]
* name: Ada
    * salary: 100
* salary: 90000
    * source: payroll
    * note: base
* diagnosis: flu
* manager -> bo

# bo [Person]
* name: Bo
'''


def _g(text=SRC):
    g = graph()
    read(text, g)
    return g


def allow(*levels):
    return lambda viewer, sensitivity: sensitivity in levels or viewer == 'root'


def _labels(g, nid):
    n = g.nodes['http://e.o/' + nid]
    return sorted(str(a.label).rsplit('/', 1)[1] for a in (*n.properties, *n.edges) if 'onya' not in str(a.label))


def test_a_property_declares_its_sensitivity_and_at_most_one():
    assert load_shapes(_g()).properties['http://e.o/salary'].sensitivity == 'partner'
    assert load_shapes(_g()).properties['http://e.o/name'].sensitivity is None
    twice = '* @sensitivity: partner\n* @sensitivity: x\n# diagnosis'
    two = _g(SRC.replace('* @sensitivity: partner\n# diagnosis', twice))
    assert [f.kind for f in validate(two).findings if f.kind == 'bad_shape']


def test_refused_labels_go_with_their_nested_assertions_and_the_rest_stays():
    g = _g()
    out = redact(g, 'viewer', allow('clinical'))  # partner refused, clinical allowed
    assert _labels(out, 'ada') == ['diagnosis', 'name']  # salary and the manager edge are gone
    assert not any(str(a.label).endswith('source') for a in out.nodes['http://e.o/ada'].properties)  # nested went too
    assert _labels(out, 'bo') == ['name']
    assert 'http://e.o/bo' in out.nodes and 'http://e.o/Person' in out.nodes  # nodes and declarations stay


def test_a_sensitive_label_nested_under_an_allowed_one_goes_too():
    out = redact(_g(), 'viewer', allow('clinical'))
    name = next(a for a in out.nodes['http://e.o/ada'].properties if str(a.label).endswith('/name'))
    assert list(name.properties) == []  # `salary: 100` was nested under name


def test_everything_allowed_changes_nothing_and_marks_nothing():
    g = _g()
    out = redact(g, 'viewer', allow('partner', 'clinical'))
    assert transient(out) == {} and _labels(out, 'ada') == _labels(g, 'ada')
    check_persistable(out)


def test_the_original_is_untouched_and_the_policy_is_asked_once_per_level():
    g, asked = _g(), []
    before = _labels(g, 'ada')

    def policy(viewer, sensitivity):
        asked.append((viewer, sensitivity))
        return False

    redact(g, 'v', policy)
    assert _labels(g, 'ada') == before
    assert sorted(asked) == [('v', 'clinical'), ('v', 'partner')]  # salary and manager share one answer


def test_nodes_that_lost_something_are_marked_and_the_others_are_not():
    out = redact(_g(), 'viewer', allow('clinical'))
    assert transient(out) == {'http://e.o/ada': ['redacted']}  # bo lost nothing
    with pytest.raises(TransientError, match='http://e.o/ada.*redacted'):
        check_persistable(out)


def test_the_mark_survives_a_text_round_trip():
    out = redact(_g(), 'viewer', allow('clinical'))
    buf = io.StringIO()
    write(out, buf)
    again = graph()
    read(buf.getvalue(), again)
    assert transient(again) == {'http://e.o/ada': ['redacted']}


def test_the_marker_says_nothing_about_what_was_withheld():
    out = redact(_g(), 'viewer', allow())
    text = io.StringIO()
    write(out, text)
    ada = text.getvalue().split('# http://e.o/ada')[1].split('\n# ')[0]  # the node's own block
    assert '@reason: redacted' in ada
    assert 'salary' not in ada and 'diagnosis' not in ada and '90000' not in text.getvalue()
    # The declarations stay (a viewer needs them to read the graph), so the schema still names `salary`
    assert 'salary [@Property]' in text.getvalue() or '/salary [@Property]' in text.getvalue()


def test_shapes_can_live_elsewhere_and_policy_is_required():
    head = '# @docheader\n* @nodebase: http://e.o/\n* @schema: http://e.o/\n\n'
    data = _g(head + '# ada [Person]\n* salary: 1\n* name: A\n')
    out = redact(data, 'v', allow(), shapes=load_shapes(_g()))
    assert _labels(out, 'ada') == ['name']
    with pytest.raises(ValueError, match='policy'):
        redact(data, 'v', None)
    assert _labels(redact(data, 'v', allow()), 'ada') == ['name', 'salary']  # no declarations in `data`: nothing known


def test_mark_is_idempotent_per_reason_and_a_hand_made_mark_counts():
    g = _g()
    n = g.nodes['http://e.o/bo']
    mark(n, 'working copy')
    mark(n, 'working copy')
    mark(n, 'second reason')
    assert transient(g) == {'http://e.o/bo': ['second reason', 'working copy']}
    h = _g(SRC + '\n# cy [Person]\n* @transient: true\n')  # authored by hand, with no reason
    assert transient(h) == {'http://e.o/cy': []}
    with pytest.raises(TransientError, match='no reason given'):
        check_persistable(h)
