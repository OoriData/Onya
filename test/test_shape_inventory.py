# -*- coding: utf-8 -*-
# test/test_shape_inventory.py
'''`onya.shape.inventory`: the open-world audit of what a graph uses that no shape declares (#83).'''

import pytest

from onya.graph import graph
from onya.serial.literate import read
from onya.shape import inventory

SRC = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# Person [@Class]

* @label: Person

# Robot [@Class]

# Person2 [@Class]

* @subClassOf -> Person

# Spare [@Class]

# name [@Property]

* @appliesTo -> Person
* @cardinality: 0..*
* @qualifier -> period

# retired [@Property]

# knows [@Property]

# al [Person]

* name: Al
    * period: 2024
    * source: a memo
* nick: Ally
* nick: Alfie
* tattoo: none
* knows -> bo

# bo [Person2 Gadget]

* name: Bo
* nick: B
* nick: Bobby
* nick: Bo-Bo
* nick: Bobo

# cy [Gizmo Gadget]

* nick: C
'''


@pytest.fixture
def inv():
    g = graph()
    read(SRC, g)
    return inventory(g)


def test_undeclared_labels_with_counts_nodes_and_examples(inv):
    # nick is used 7 times on 3 nodes; tattoo once; name and knows are declared; reserved terms never appear
    got = {k.rsplit('/', 1)[1]: (e.count, e.nodes) for k, e in inv.labels.items()}
    assert got == {'nick': (7, 3), 'tattoo': (1, 1)}
    nick = inv.labels['http://e.o/nick']
    assert nick.examples == [('http://e.o/al', 'Alfie'), ('http://e.o/al', 'Ally'), ('http://e.o/bo', 'B')]


def test_most_used_first_then_by_iri(inv):
    assert list(inv.labels) == ['http://e.o/nick', 'http://e.o/tattoo']
    assert list(inv.types) == ['http://e.o/Gadget', 'http://e.o/Gizmo']  # 2 nodes, then 1


def test_undeclared_types(inv):
    assert {k.rsplit('/', 1)[1]: e.count for k, e in inv.types.items()} == {'Gadget': 2, 'Gizmo': 1}
    assert inv.types['http://e.o/Gadget'].examples == ['http://e.o/bo', 'http://e.o/cy']
    assert 'http://e.o/Person' not in inv.types


def test_nested_labels_counted_apart_and_qualifiers_are_covered(inv):
    # `source` is undeclared and nested; `period` is a declared @qualifier so it is covered; `name` is declared
    assert list(inv.nested_labels) == ['http://e.o/source']
    assert inv.nested_labels['http://e.o/source'].examples == [('http://e.o/al', 'a memo')]
    assert 'http://e.o/source' not in inv.labels


def test_declared_but_unused(inv):
    # Robot, Spare nothing is typed with; Person is used via al (directly) and Person2 (a subclass)
    assert inv.declared_unused == {'labels': ['http://e.o/retired'], 'types': ['http://e.o/Robot', 'http://e.o/Spare']}


def test_a_class_used_only_through_a_subclass_is_used():
    g = graph()
    read('''# @docheader

* @nodebase: http://e.o/
* @schema: http://e.o/

# Base [@Class]

# Sub [@Class]

* @subClassOf -> Base

# x [Sub]
''', g)
    assert inventory(g).declared_unused['types'] == []


def test_closed_class_labels_are_still_inventoried():
    g = graph()
    read('''# @docheader

* @nodebase: http://e.o/
* @schema: http://e.o/

# Thing [@Class]

* @closed: true

# x [Thing]

* mystery: 1
''', g)
    assert list(inventory(g).labels) == ['http://e.o/mystery']


def test_declarations_and_reserved_terms_are_not_inventoried(inv):
    everything = [*inv.labels, *inv.types, *inv.nested_labels]
    assert not any('purl.org/onya' in k for k in everything)  # @label, @appliesTo, @Class, ... are not data
    assert 'http://e.o/Person' not in everything and 'http://e.o/name' not in everything


def test_examples_limit_and_zero(inv):
    g = graph()
    read(SRC, g)
    assert len(inventory(g, examples=1).labels['http://e.o/nick'].examples) == 1
    zero = inventory(g, examples=0)
    assert zero.labels['http://e.o/nick'].examples == [] and zero.labels['http://e.o/nick'].count == 7


def test_shapes_in_a_separate_graph_and_report_is_stable():
    data, decl = graph(), graph()
    read(SRC, data)
    read('# @docheader\n\n* @nodebase: http://e.o/\n* @schema: http://e.o/\n\n# nick [@Property]\n', decl)
    inv = inventory(data, decl)
    assert 'http://e.o/nick' not in inv.labels and 'http://e.o/name' in inv.labels  # only `decl` declares anything
    again = inventory(data, decl)
    assert str(inv) == str(again)


def test_str_lists_counts_examples_and_unused(inv):
    text = str(inv)
    assert 'undeclared labels:' in text and 'nick' in text and 'e.g. http://e.o/al Alfie' in text
    assert 'declared but unused types:' in text and 'http://e.o/Spare' in text
    assert str(inventory(graph())) == 'Inventory: nothing undeclared, nothing unused'


HEAD = '# @docheader\n\n* @nodebase: http://e.o/\n* @schema: http://e.o/\n\n'


def _inv(body, shapes=''):
    g = graph()
    read(HEAD + shapes + body, g)
    return inventory(g)


def test_order_is_by_count_not_alphabet():
    inv = _inv('# x [T]\n\n* zebra: 1\n* zebra: 2\n* apple: 1\n\n# y [T]\n\n* zebra: 3\n')
    assert list(inv.labels) == ['http://e.o/zebra', 'http://e.o/apple']  # 3 uses before 1, though 'apple' sorts first


def test_examples_are_the_first_in_node_order_whatever_the_read_order():
    body = ''.join(f'# n{i:02}\n\n* tag: v\n\n' for i in range(30, 0, -1))
    assert [ex[0] for ex in _inv(body).labels['http://e.o/tag'].examples] == [f'http://e.o/n{i:02}' for i in (1, 2, 3)]


def test_declaration_nodes_are_not_data():
    inv = _inv('', '# p [@Property]\n\n* remark: free text\n\n# C [@Class]\n\n* remark: free text\n\n')
    assert inv.labels == {}  # `remark` hangs only on declarations


def test_reserved_labels_on_data_nodes_are_not_inventoried():
    inv = _inv('# x [T]\n\n* @label: An X\n* custom: 1\n')
    assert list(inv.labels) == ['http://e.o/custom']


def test_a_property_held_in_a_sidecar_is_not_reported_unused():
    inv = _inv('# x [T]\n\n* a: 1\n', '# gpa [@Property]\n\n* @circumQuery -> grades\n\n# grades [@Sidecar]\n\n'
               '# idle [@Property]\n\n')
    assert inv.declared_unused['labels'] == ['http://e.o/idle']  # gpa's values live in the sidecar, not the graph


def test_cli_inventory_prints_the_report_and_exits_clean(tmp_path, capsys):
    from onya.cli.onya import inventory as cli_inventory
    (tmp_path / 'kg.onya').write_text(SRC)
    cli_inventory(str(tmp_path / 'kg.onya'), examples=1)  # no SystemExit: an audit, not a check
    out = capsys.readouterr().out
    assert out.index('http://e.o/nick') < out.index('http://e.o/tattoo')
    assert 'undeclared types:' in out and 'declared but unused labels:' in out
    assert out.count('e.g.') == 5  # one each: nick, tattoo, Gadget, Gizmo, source
    (tmp_path / 'shapes.onya').write_text(HEAD + '# nick [@Property]\n')
    cli_inventory(str(tmp_path / 'kg.onya'), shapes=str(tmp_path / 'shapes.onya'), examples=0)
    out = capsys.readouterr().out
    assert 'e.g.' not in out and 'http://e.o/nick' not in out and 'http://e.o/tattoo' in out
