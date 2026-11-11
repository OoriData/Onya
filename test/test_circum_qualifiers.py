# -*- coding: utf-8 -*-
# test/test_circum_qualifiers.py
'''
Qualifiers and attributes on circum values (`@qualifier`, `@attribute`): a ledger of values per node told apart
by a nested label such as `period`, projected, resolved, written and moved by `emit`. SQLite; the PostgreSQL path
is in `test/store/test_store_postgres.py`.

    pytest -s test/test_circum_qualifiers.py
'''

import sqlite3

import pytest

from onya.circum import (CircumError, Context, Registry, Sidecar, Text, augment, emit, from_shapes, materialize,
                         rows, statements, strip, table_resolvers, table_writers)
from onya.digest import digest
from onya.serial.literate import read

NS = 'http://e.o/'
PERSON = NS + 'Person'
COMP, RATE, PERIOD, UNIT = (NS + x for x in ('compensation', 'rate', 'period', 'unit'))

HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
'''

SHAPES = '''
# Person [@Class]

# compensation [@Property]
* @appliesTo -> Person
* @as: number
* @cardinality: 0..*
* @circumQuery -> payroll
* @qualifier -> period
* @attribute -> unit

# period [@Property]
* @as: text

# unit [@Property]
* @as: text

# payroll [@Sidecar]
* @label: Payroll
* @system -> hr
* @table: person

# hr [@System]
* @label: HR system
'''

LEDGER = '''
# adat [Person]
* compensation: 5000
  * period: 2026-Q1
  * unit: month
* compensation: 5000
  * period: 2026-Q2
  * unit: month
* compensation: 60
  * unit: hour

# chuks [Person]
'''

BARE = HEAD + SHAPES + '''
# adat [Person]

# chuks [Person]
'''
FULL = HEAD + SHAPES + LEDGER


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    yield c
    c.close()


def registry(p):
    reg = Registry()
    reg.resolvers.update(table_resolvers(p))
    reg.writers.update(table_writers(p))
    return reg


async def projected(conn, text=FULL):
    g = read(text).graph
    p = from_shapes(g, PERSON)
    await materialize(conn, p, g)
    return g, p


def ledger(conn):
    return conn.execute('SELECT person_id, value, period, unit FROM person_compensation '
                        'ORDER BY person_id, period').fetchall()


def nested(a, label):
    return [c.value for c in a.getprop(label)]


# --- the projection ---------------------------------------------------------------------

def test_qualifiers_are_the_key_and_attributes_ride_along():
    p = from_shapes(read(FULL).graph, PERSON)
    (t,) = [t for t in p.tables if t.parent]
    assert [(c.name, c.kind, c.nullable) for c in t.columns] == [
        ('person_id', 'id', False), ('value', 'value', False), ('period', 'qualifier', False),
        ('unit', 'attribute', True)]
    assert t.key == ('person_id', 'period')  # the value is not in the key: the same amount recurs
    assert 'PRIMARY KEY (person_id, period)' in statements(p, 'sqlite')[1]


def test_a_property_without_qualifiers_keeps_its_key():
    text = FULL.replace('* @qualifier -> period\n', '').replace('* @attribute -> unit\n', '')
    (t,) = [t for t in from_shapes(read(text).graph, PERSON).tables if t.parent]
    assert t.key == ('person_id', 'value') and not t.extras


@pytest.mark.parametrize('change, why', [
    (lambda s: s.replace('# period [@Property]\n* @as: text\n', ''), 'not declared as a @Property'),
    (lambda s: s.replace('* @cardinality: 0..*', '* @cardinality: 0..1'), 'several values'),
    (lambda s: s.replace('* @cardinality: 0..*', '* @cardinality: 0..*\n* @ordered: true'), 'several values'),
])
def test_a_declaration_that_cannot_be_a_column_is_refused(change, why):
    with pytest.raises(CircumError, match=why):
        from_shapes(read(change(FULL)).graph, PERSON)


# --- rows -------------------------------------------------------------------------------

def test_the_same_value_in_two_periods_is_two_rows_and_no_period_is_one_unqualified_row():
    g = read(FULL).graph
    out = rows(from_shapes(g, PERSON), g)['person_compensation']
    assert [(r[2], r[3], str(r[1])) for r in out] == [('', 'hour', '60'), ('2026-Q1', 'month', '5000'),
                                                      ('2026-Q2', 'month', '5000')]


def test_one_key_with_two_values_is_a_conflict_that_names_the_node_and_line():
    text = FULL.replace('* compensation: 60\n  * unit: hour', '* compensation: 5100\n  * period: 2026-Q1')
    g = read(text, track_locations=True).graph
    with pytest.raises(CircumError) as e:
        rows(from_shapes(g, PERSON), g)
    msg = str(e.value)
    assert 'adat' in msg and 'compensation' in msg and "period='2026-Q1'" in msg and 'conflict' in msg
    assert 'http://e.o/doc:' in msg  # the line it was written on


def test_an_identical_repeat_is_not_a_conflict_but_a_different_attribute_is():
    again = '* compensation: 5000\n  * period: 2026-Q1\n  * unit: month\n'
    dup = FULL.replace('* compensation: 60', again + '* compensation: 60')
    g = read(dup).graph
    assert len(rows(from_shapes(g, PERSON), g)['person_compensation']) == 3
    other = dup.replace('  * unit: month\n* compensation: 60', '  * unit: year\n* compensation: 60', 1)
    g = read(other).graph
    with pytest.raises(CircumError, match='conflict'):
        rows(from_shapes(g, PERSON), g)


def test_a_typed_qualifier_cannot_be_absent():
    text = FULL.replace('# period [@Property]\n* @as: text', '# period [@Property]\n* @as: integer')
    text = text.replace('period: 2026-Q1', 'period: 2026').replace('period: 2026-Q2', 'period: 2027')
    g = read(text).graph
    with pytest.raises(CircumError, match='part of the key'):  # the unit: hour value has no period
        rows(from_shapes(g, PERSON), g)


# --- augment / strip ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_view_shows_the_values_with_their_nested_period_and_strips_clean(conn):
    _, p = await projected(conn)
    bare = read(BARE).graph
    view = await augment(bare, registry=registry(p), conn=conn)
    vals = sorted((a.value, tuple(nested(a, PERIOD)), tuple(nested(a, UNIT))) for a in view[NS + 'adat'].getprop(COMP))
    assert vals == [('5000', ('2026-Q1',), ('month',)), ('5000', ('2026-Q2',), ('month',)), ('60', (), ('hour',))]
    assert digest(strip(view)) == digest(bare)  # nested qualifiers go with the value that carried them


@pytest.mark.asyncio
async def test_an_authored_value_in_another_period_does_not_hide_the_stored_one(conn):
    _, p = await projected(conn)
    g = read(BARE).graph
    a = g[NS + 'adat'].add_property(COMP, '5000')  # authored: 5000 with no period
    a.add_property(PERIOD, '2025-Q4')
    view = await augment(g, registry=registry(p), conn=conn)
    assert sorted(tuple(nested(c, PERIOD)) for c in view[NS + 'adat'].getprop(COMP)) == [
        (), ('2025-Q4',), ('2026-Q1',), ('2026-Q2',)]


# --- emit --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emit_moves_qualified_values_out_of_the_graph_and_the_view_gives_them_back(conn):
    _, p = await projected(conn, BARE)
    reg = registry(p)
    g = read(FULL).graph
    report = await emit(g, registry=reg, conn=conn)
    assert len(report.moved) == 3 and not report.review
    assert list(g[NS + 'adat'].getprop(COMP)) == []  # they left the graph, nested assertions with them
    assert ledger(conn) == [(NS + 'adat', 60, '', 'hour'), (NS + 'adat', 5000, '2026-Q1', 'month'),
                            (NS + 'adat', 5000, '2026-Q2', 'month')]
    view = await augment(g, registry=reg, conn=conn)
    assert digest(strip(view)) == digest(g)
    assert sorted((a.value, tuple(nested(a, PERIOD))) for a in view[NS + 'adat'].getprop(COMP)) == [
        ('5000', ('2026-Q1',)), ('5000', ('2026-Q2',)), ('60', ())]


@pytest.mark.asyncio
async def test_emitting_again_is_idempotent_and_does_not_touch_updated(conn):
    g, p = await projected(conn)
    before = conn.execute('SELECT * FROM person_compensation ORDER BY 1, 3').fetchall()
    await emit(read(FULL).graph, registry=registry(p), conn=conn)
    assert conn.execute('SELECT * FROM person_compensation ORDER BY 1, 3').fetchall() == before


@pytest.mark.asyncio
async def test_an_undeclared_nested_assertion_still_goes_to_review(conn):
    _, p = await projected(conn, BARE)
    text = FULL.replace('  * unit: hour', '  * unit: hour\n  * note: negotiated')
    g = read(text).graph
    report = await emit(g, registry=registry(p), conn=conn)
    assert len(report.moved) == 2 and len(report.review) == 1  # the noted one stays, whole, in the graph
    (left,) = g[NS + 'adat'].getprop(COMP)
    assert left.value == '60' and nested(left, NS + 'note') == ['negotiated']
    assert len(ledger(conn)) == 2


@pytest.mark.asyncio
async def test_a_changed_amount_is_a_conflict_and_nothing_is_written_or_removed(conn):
    _, p = await projected(conn)
    before = ledger(conn)
    g = read(HEAD + SHAPES + '''
# adat [Person]
* compensation: 5000
  * period: 2026-Q3
  * unit: month
* compensation: 5100
  * period: 2026-Q1
  * unit: month
''').graph
    with pytest.raises(CircumError) as e:
        await emit(g, registry=registry(p), conn=conn)
    assert "period='2026-Q1'" in str(e.value) and 'for a person to decide' in str(e.value)
    assert ledger(conn) == before  # not even the new Q3 row: all or nothing
    assert len(list(g[NS + 'adat'].getprop(COMP))) == 2  # and the graph kept both


@pytest.mark.asyncio
async def test_one_batch_giving_a_key_two_contents_is_a_conflict(conn):
    _, p = await projected(conn, BARE)
    w = table_writers(p)[COMP]
    ctx = Context(COMP, Sidecar(NS + 'payroll', table='person'), None, None, None, conn)
    rows_ = {NS + 'adat': [Text('1', qualifiers={PERIOD: 'x'}), Text('2', qualifiers={PERIOD: 'x'})]}
    with pytest.raises(CircumError, match='for a person to decide'):
        await w(rows_, ctx)
    assert ledger(conn) == []


@pytest.mark.asyncio
async def test_a_writer_refuses_a_label_it_has_no_column_for(conn):
    _, p = await projected(conn, BARE)
    ctx = Context(COMP, Sidecar(NS + 'payroll', table='person'), None, None, None, conn)
    with pytest.raises(CircumError, match='no qualifier column'):
        await table_writers(p)[COMP]({NS + 'adat': [Text('1', qualifiers={NS + 'region': 'eu'})]}, ctx)
    with pytest.raises(CircumError, match='no attribute column'):
        await table_writers(p)[COMP]({NS + 'adat': [Text('1', attributes={PERIOD: 'x'})]}, ctx)  # not an attribute


# --- a hand-written ledger (no projection): the contract alone -----------------------------

@pytest.mark.asyncio
async def test_a_hand_written_writer_receives_the_qualifiers_and_a_resolver_can_return_them():
    held = {}
    reg = Registry()

    @reg.writer(COMP)
    async def write(batch, ctx):
        for s, items in batch.items():
            held[s] = [(i.value, i.qualifiers, i.attributes) for i in items]

    @reg.resolver(COMP)
    async def resolve(subjects, ctx):
        return {NS + 'adat': [Text('7', qualifiers={PERIOD: '2030'}, attributes={UNIT: 'week'})]}

    g = read(FULL).graph
    await emit(g, registry=reg)
    assert sorted(held[NS + 'adat'], key=lambda t: t[1].get(PERIOD, '')) == [
        ('60', {}, {UNIT: 'hour'}), ('5000', {PERIOD: '2026-Q1'}, {UNIT: 'month'}),
        ('5000', {PERIOD: '2026-Q2'}, {UNIT: 'month'})]
    view = await augment(read(BARE).graph, registry=reg)
    (a,) = view[NS + 'adat'].getprop(COMP)
    assert nested(a, PERIOD) == ['2030'] and nested(a, UNIT) == ['week']
