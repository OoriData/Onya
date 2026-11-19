# -*- coding: utf-8 -*-
# test/test_shape_nested.py
'''
#86: the order of a declaration's lists (`@oneOf`, `@qualifier`, `@attribute`, `@replacedBy`) comes from the
ordering layer, a declared label's `@range` / `@oneOf` / deprecation hold when it is nested under an assertion,
and `uses()` lists where declared labels are used.
'''

from onya.circum import from_shapes
from onya.graph import graph
from onya.serial.literate import read
from onya.shape import load_shapes, uses, validate

NS = 'http://e.o/'


def head(ordered=''):
    return ('# @docheader\n* @document: http://e.o/doc\n* @nodebase: http://e.o/\n* @schema: http://e.o/\n'
            + (f'* @ordered: {ordered}\n' if ordered else ''))


def _g(text):
    g = graph()
    read(text, g)
    return g


STATUS = '''
# status [@Property]
* @oneOf: lead
* @oneOf: active
* @oneOf: closed
'''

QUALS = '''
# fee [@Property]
* @cardinality: 0..*
* @qualifier -> zeta
* @qualifier -> alpha
* @qualifier -> mid
* @attribute -> yen
* @attribute -> bar
# zeta [@Property]
# alpha [@Property]
# mid [@Property]
# yen [@Property]
# bar [@Property]
'''


# --- the order of a declaration's lists ---------------------------------------------------

def test_unstamped_lists_are_sorted_not_in_set_order():
    sh = load_shapes(_g(head() + STATUS + QUALS))
    assert sh.properties[NS + 'status'].one_of == ('active', 'closed', 'lead')
    assert sh.properties[NS + 'fee'].qualifiers == (NS + 'alpha', NS + 'mid', NS + 'zeta')
    assert sh.properties[NS + 'fee'].attributes == (NS + 'bar', NS + 'yen')


def test_an_ordered_stanza_gives_the_order_the_author_wrote():
    sh = load_shapes(_g(head('@oneOf @qualifier @attribute @replacedBy') + STATUS + QUALS + '''
# old [@Property]
* @replacedBy -> new2
* @replacedBy -> new1
# new1 [@Property]
# new2 [@Property]
'''))
    assert sh.problems == []
    assert sh.properties[NS + 'status'].one_of == ('lead', 'active', 'closed')  # a lifecycle, not the alphabet
    assert sh.properties[NS + 'fee'].qualifiers == (NS + 'zeta', NS + 'alpha', NS + 'mid')
    assert sh.properties[NS + 'fee'].attributes == (NS + 'yen', NS + 'bar')
    assert sh.properties[NS + 'old'].replaced_by == (NS + 'new2', NS + 'new1')


def test_stamps_written_by_hand_work_too():
    sh = load_shapes(_g(head() + '''
# status [@Property]
* @oneOf: b
  * @ordering: 2
* @oneOf: a
  * @ordering: 1
'''))
    assert sh.properties[NS + 'status'].one_of == ('a', 'b')


def test_the_qualifier_order_is_the_order_of_the_key_columns():
    shapes = head('@qualifier') + '''
# Person [@Class]
# fee [@Property]
* @appliesTo -> Person
* @as: number
* @cardinality: 0..*
* @circumQuery -> pay
* @qualifier -> zeta
* @qualifier -> alpha
# zeta [@Property]
# alpha [@Property]
# pay [@Sidecar]
* @system -> hr
* @table: person
# hr [@System]
'''
    (t,) = [t for t in from_shapes(_g(shapes), NS + 'Person').tables if t.parent]
    assert t.key == ('person_id', 'zeta', 'alpha')


def test_a_half_stamped_list_is_a_bad_shape_and_falls_back_to_sorted():
    sh = load_shapes(_g(head() + '''
# status [@Property]
* @oneOf: lead
  * @ordering: 1
* @oneOf: closed
* @oneOf: active
'''))
    assert sh.properties[NS + 'status'].one_of == ('active', 'closed', 'lead')
    (f,) = sh.problems
    assert f.kind == 'bad_shape' and 'no @ordering' in f.detail and f.node == NS + 'status'


def test_the_one_of_finding_lists_the_values_in_declared_order():
    g = _g(head('@oneOf') + STATUS + '\n# Thing [@Class]\n# x [Thing]\n* status: dormant\n')
    (f,) = [f for f in validate(g).findings if f.kind == 'one_of']
    assert "['lead', 'active', 'closed']" in f.detail


# --- nested assertions --------------------------------------------------------------------

NESTED = head() + '''
# Role [@Class]
# Person [@Class]
# assigned [@Property]
# role [@Property]
* @range -> Role
# roleName [@Property]
* @oneOf: lead
* @oneOf: member
* @deprecated: Use role.
# note [@Property]
* @as: integer

# editor [Role]
# ada [Person]
* assigned: team
    * role -> editor
    * roleName: lead
# bo [Person]
* assigned: team
    * role -> ada
    * roleName: boss
    * note: x
'''


def _kinds(report):
    return sorted((f.kind, str(f.node).rsplit('/', 1)[1], str(f.label).rsplit('/', 1)[1]) for f in report.findings)


def test_range_and_one_of_hold_for_nested_assertions_of_a_declared_property():
    r = validate(_g(NESTED))
    got = [(k, n, lab) for k, n, lab in _kinds(r) if k != 'deprecated']
    assert got == [('one_of', 'bo', 'roleName'), ('range', 'bo', 'role')]
    detail = next(f.detail for f in r.findings if f.kind == 'range')
    assert detail.startswith('nested under http://e.o/assigned: ') and 'http://e.o/ada' in detail
    located = graph()
    read(NESTED, located, track_locations=True)
    assert 'http://e.o/doc:' in str(next(f for f in validate(located).findings if f.kind == 'range'))  # names the line


def test_applies_to_and_cardinality_stay_with_a_nodes_own_assertions():
    text = head() + """
# Role [@Class]
# Person [@Class]
# role [@Property]
* @range -> Role
* @appliesTo -> Role
* @cardinality: 0..1
# editor [Role]
# ada [Person]
* assigned: team
    * role -> editor
    * role -> editor
    * role -> ada
"""
    kinds = [(f.kind, f.detail[:12]) for f in validate(_g(text)).findings]
    assert kinds == [('range', 'nested under')]  # `ada` is no Role and holds 3 roles, but only the target is checked


def test_a_nested_value_does_not_get_the_shapes_as_default():
    # `note: x` under bo is nested, and `note` is declared `@as: integer`: the default stays with node-level values
    assert not [f for f in validate(_g(NESTED)).findings if f.kind == 'as']


def test_a_deprecated_label_is_reported_for_nested_uses_once_per_node():
    r = validate(_g(NESTED))
    dep = sorted((str(f.node).rsplit('/', 1)[1], f.detail) for f in r.findings if f.kind == 'deprecated')
    assert [n for n, _ in dep] == ['ada', 'bo']
    assert all(d.startswith('nested under http://e.o/assigned: label http://e.o/roleName is deprecated: Use role.')
               for _, d in dep)
    twice = NESTED.replace('# ada [Person]\n', '# ada [Person]\n* roleName: lead\n')  # also on the node itself
    ada = [f for f in validate(_g(twice)).findings if f.kind == 'deprecated' and f.node == NS + 'ada']
    assert len(ada) == 1 and not ada[0].detail.startswith('nested')  # the node's own use is the one reported


def test_nesting_deeper_is_still_checked():
    deep = head() + '''
# Role [@Class]
# role [@Property]
* @range -> Role
# x [Thing]
* a: 1
    * b: 2
        * c: 3
            * role -> x
'''
    (f,) = [f for f in validate(_g(deep)).findings if f.kind == 'range']
    assert f.detail.startswith('nested under http://e.o/c: ')


def test_undeclared_nested_labels_and_reserved_ones_are_left_alone():
    g = _g(head() + '# x [Thing]\n* a: 1\n    * whatever: 2\n    * @source: memo\n')
    assert validate(g).ok and not validate(g).findings


# --- uses ---------------------------------------------------------------------------------

SECRET = '# secret [@Property]\n* @sensitivity: partner\n# note [@Property]'
WITH_SECRETS = '* secret: s1\n* assigned: team\n    * secret: s2\n    * role -> editor'
USES = NESTED.replace('# note [@Property]', SECRET).replace('* assigned: team\n    * role -> editor', WITH_SECRETS)


def test_uses_filters_declared_labels_by_a_predicate_on_their_shape():
    u = uses(_g(USES), where=lambda p: p.sensitivity)
    assert list(u.labels) == [NS + 'secret'] and list(u.nested_labels) == [NS + 'secret']
    assert (u.labels[NS + 'secret'].count, u.labels[NS + 'secret'].nodes) == (1, 1)
    assert u.nested_labels[NS + 'secret'].examples == [(NS + 'ada', 's2')]  # the node whose assertion holds it
    dep = uses(_g(USES), where=lambda p: p.deprecated is not None)
    assert list(dep.nested_labels) == [NS + 'roleName'] and not dep.labels
    assert dep.nested_labels[NS + 'roleName'].count == 2 and dep.nested_labels[NS + 'roleName'].nodes == 2


def test_uses_without_a_predicate_lists_every_declared_label_most_used_first():
    u = uses(_g(USES))
    assert list(u.nested_labels)[:2] == [NS + 'role', NS + 'roleName']  # 2 each, then by IRI
    assert NS + 'whatever' not in u.nested_labels and not any('purl.org' in k for k in (*u.labels, *u.nested_labels))


def test_uses_takes_shapes_from_elsewhere_and_examples_and_prints():
    data = _g(head() + '# x [Thing]\n* secret: 1\n* secret: 2\n* secret: 3\n')
    decl = _g(head() + '# secret [@Property]\n* @sensitivity: partner\n')
    u = uses(data, decl, where=lambda p: p.sensitivity == 'partner', examples=2)
    assert len(u.labels[NS + 'secret'].examples) == 2 and u.labels[NS + 'secret'].count == 3
    assert 'labels:' in str(u) and 'e.g. http://e.o/x 1' in str(u)
    assert str(uses(data, decl, where=lambda p: False)) == 'Uses: none'
    assert uses(_g(head() + '# secret [@Property]\n'), where=None).labels == {}  # declared, never used
