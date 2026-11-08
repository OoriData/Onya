# -*- coding: utf-8 -*-
# test/test_circum_tables.py
'''
Resolvers and writers derived from a `Projection` (`onya.circum.table_resolvers`, `table_writers`), the
per-row `updated` column and the schema check, over SQLite. The PostgreSQL path is in the opt-in store test.

    pytest -s test/test_circum_tables.py
'''

import sqlite3

import pytest

from onya.circum import (CircumError, Context, Registry, Sidecar, augment, emit, from_shapes, materialize, strip,
                         table_resolvers, table_writers)
from onya.digest import digest
from onya.serial.literate import read

NS = 'http://e.o/'
STUDENT = NS + 'Student'
COUNSELLED_BY, GPA, INTEREST, NICKNAME, NAME = (NS + x for x in ('counselledBy', 'gpa', 'interest', 'nickname', 'name'))
CIRCUM = (COUNSELLED_BY, GPA, INTEREST, NICKNAME)

HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
* @ordered: nickname
'''

SHAPES = '''
# Student [@Class]
# Person [@Class]

# name [@Property]
* @appliesTo -> Student
* @appliesTo -> Person
* @as: text

# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @circumQuery -> students-db
  * @queryDetail: counsellor_for_students

# gpa [@Property]
* @appliesTo -> Student
* @as: number
* @circumQuery -> students-db

# interest [@Property]
* @appliesTo -> Student
* @cardinality: 0..*
* @circumQuery -> students-db

# nickname [@Property]
* @appliesTo -> Student
* @cardinality: 0..*
* @ordered: true
* @circumQuery -> students-db

# students-db [@Sidecar]
* @label: Student records
* @system -> uni
* @table: student
* @sensitivity: internal

# uni [@System]
* @label: University database

# adat [Person]
* name: Adat Okon
'''

# the same students, with and without what the sidecar holds
FULL = HEAD + SHAPES + '''
# chuks [Student]
* name: Chuks
* counselledBy -> adat
* gpa: 3.4
* interest: chess
* interest: music
* nickname: Zed
* nickname: Abe

# dede [Student]
* name: Dede
'''

BARE = HEAD + SHAPES + '''
# chuks [Student]
* name: Chuks

# dede [Student]
* name: Dede
'''


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
    full = read(text).graph
    p = from_shapes(full, STUDENT)
    await materialize(conn, p, full)
    return full, p


def held(g, node, label):
    '''What node `node` of `g` says under `label`: values and edge targets, sorted.'''
    n = g[NS + node]
    return sorted([a.value for a in n.getprop(label)] + [str(e.target.id) for e in n.getedge(label)])


def ctx(label, table='student', conn=None):
    return Context(label, Sidecar(NS + 'students-db', table=table), None, None, None, conn)


@pytest.mark.asyncio
async def test_what_a_projection_holds_comes_back_through_a_view(conn):
    full, p = await projected(conn)
    bare = read(BARE).graph
    view = await augment(bare, registry=registry(p), conn=conn)
    for label in CIRCUM:
        assert held(view, 'chuks', label) == held(full, 'chuks', label), label
        assert held(view, 'dede', label) == []
    assert digest(strip(view)) == digest(bare)


@pytest.mark.asyncio
async def test_asof_is_the_rows_own_updated_time(conn):
    _, p = await projected(conn)
    view = await augment(read(BARE).graph, registry=registry(p), conn=conn)
    (e,) = view[NS + 'chuks'].getedge(COUNSELLED_BY)
    (stamp,) = e.getprop('@asOf')
    (stored,) = conn.execute("SELECT updated FROM student WHERE id = 'http://e.o/chuks'").fetchone()
    assert stamp.value == stored[:19] + 'Z'


@pytest.mark.asyncio
async def test_updated_changes_only_with_the_row(conn):
    full, p = await projected(conn)
    before = conn.execute('SELECT id, updated FROM student ORDER BY id').fetchall()
    report = await materialize(conn, p, full)  # nothing changed in the graph
    assert report.unchanged and not (report.inserted or report.updated)
    assert conn.execute('SELECT id, updated FROM student ORDER BY id').fetchall() == before
    full[NS + 'chuks'].add_property(GPA, '3.5')  # a second gpa is a conflict: change the one value instead
    for a in list(full[NS + 'chuks'].getprop(GPA)):
        full[NS + 'chuks'].remove_property(a)
    full[NS + 'chuks'].add_property(GPA, '3.5')
    await materialize(conn, p, full)
    after = dict(conn.execute('SELECT id, updated FROM student').fetchall())
    assert after[NS + 'chuks'] > dict(before)[NS + 'chuks']  # the changed row is re-stamped
    assert after[NS + 'dede'] == dict(before)[NS + 'dede']  # the untouched one is not


@pytest.mark.asyncio
async def test_a_child_table_orders_by_ordinal_and_an_ordered_label_has_no_writer(conn):
    _, p = await projected(conn)
    reg = registry(p)
    out = await reg.resolvers[NICKNAME]([NS + 'chuks'], ctx(NICKNAME, conn=conn))
    assert [t.value for t in out[NS + 'chuks']] == ['Zed', 'Abe']  # authored order, not alphabetical
    assert NICKNAME not in reg.writers and INTEREST in reg.writers  # emit leaves ordered values for review


@pytest.mark.asyncio
async def test_emit_writes_values_into_the_table_and_a_view_reads_them(conn):
    _, p = await projected(conn)
    reg = registry(p)
    g = read(BARE).graph
    dede = g[NS + 'dede']
    dede.add_edge(COUNSELLED_BY, g[NS + 'adat'])
    dede.add_property(GPA, '3.9')
    dede.add_property(INTEREST, 'reading')
    report = await emit(g, [NS + 'dede'], registry=reg, conn=conn)
    assert len(report.moved) == 3 and not report.review
    assert held(g, 'dede', GPA) == [] and held(g, 'dede', INTEREST) == []  # they left the graph
    view = await augment(read(BARE).graph, registry=reg, conn=conn)
    assert held(view, 'dede', COUNSELLED_BY) == [NS + 'adat']
    assert held(view, 'dede', GPA) == ['3.9'] and held(view, 'dede', INTEREST) == ['reading']
    assert held(view, 'chuks', INTEREST) == ['chess', 'music']  # what was there is untouched


@pytest.mark.asyncio
async def test_emitting_the_same_values_again_changes_nothing(conn):
    _, p = await projected(conn)
    reg = registry(p)

    async def once():
        g = read(BARE).graph
        g[NS + 'dede'].add_property(GPA, '3.9')
        g[NS + 'dede'].add_property(INTEREST, 'reading')
        await emit(g, [NS + 'dede'], registry=reg, conn=conn)
        return (conn.execute('SELECT * FROM student ORDER BY id').fetchall(),
                conn.execute('SELECT * FROM student_interest ORDER BY 1, 2').fetchall())
    first = await once()
    assert await once() == first  # idempotent: same rows, and the stamps are not rewritten


@pytest.mark.asyncio
async def test_a_node_with_no_row_is_refused_naming_the_required_columns(conn):
    text = FULL.replace('# gpa [@Property]\n* @appliesTo -> Student\n* @as: number',
                        '# gpa [@Property]\n* @appliesTo -> Student\n* @as: number\n* @cardinality: 1')
    text = text.replace('# dede [Student]\n* name: Dede', '# dede [Student]\n* name: Dede\n* gpa: 3.0')
    _, p = await projected(conn, text)
    g = read(text.replace('* gpa: 3.4\n', '').replace('* gpa: 3.0\n', '')).graph
    g.node(NS + 'eve', ['Student'])  # no row in the table yet
    g[NS + 'eve'].add_edge(COUNSELLED_BY, g[NS + 'adat'])
    with pytest.raises(CircumError, match=r"no row in student.*\['gpa'\]"):
        await emit(g, [NS + 'eve'], registry=registry(p), conn=conn)
    assert held(g, 'eve', COUNSELLED_BY) == [NS + 'adat']  # nothing left the graph
    assert conn.execute("SELECT count(*) FROM student WHERE id = 'http://e.o/eve'").fetchone() == (0,)


@pytest.mark.asyncio
async def test_an_edge_to_a_node_with_no_row_is_refused(conn):
    _, p = await projected(conn)
    g = read(BARE).graph
    g.node(NS + 'stranger', ['Person'])  # a Person the table has never heard of
    g[NS + 'dede'].add_edge(COUNSELLED_BY, g[NS + 'stranger'])
    with pytest.raises(CircumError, match='not in table person'):
        await emit(g, [NS + 'dede'], registry=registry(p), conn=conn)


@pytest.mark.asyncio
async def test_a_table_missing_updated_is_a_contract_error(conn):
    full, p = await projected(conn)
    conn.execute('ALTER TABLE student DROP COLUMN updated')  # as a table made by 0.6.0 would be
    with pytest.raises(CircumError, match=r"student no longer follows.*missing \['updated'\].*0\.6\.1"):
        await materialize(conn, p, full)
    with pytest.raises(CircumError, match='missing'):
        await augment(read(BARE).graph, registry=registry(p), conn=conn)


@pytest.mark.asyncio
async def test_an_altered_table_is_a_contract_error(conn):
    full, p = await projected(conn)
    conn.execute('ALTER TABLE student ADD COLUMN nick TEXT')  # somebody's own change
    with pytest.raises(CircumError, match=r"unexpected \['nick'\]"):
        await materialize(conn, p, full)
    g = read(BARE).graph
    g[NS + 'dede'].add_property(GPA, '3.9')
    with pytest.raises(CircumError, match='unexpected'):
        await emit(g, registry=registry(p), conn=conn)


@pytest.mark.asyncio
async def test_a_column_named_updated_is_refused():
    text = FULL.replace('# interest [@Property]', '# updated [@Property]\n* @appliesTo -> Student\n* @as: text\n\n'
                        '# interest [@Property]')
    with pytest.raises(CircumError, match="'updated'.*@column"):
        from_shapes(read(text).graph, STUDENT)


@pytest.mark.asyncio
async def test_the_sidecars_table_must_be_the_one_holding_the_property(conn):
    _, p = await projected(conn)
    wrong = BARE.replace('* @table: student', '* @table: pupils')
    with pytest.raises(CircumError, match="declares @table 'pupils'.*'student'"):
        await augment(read(wrong).graph, registry=registry(p), conn=conn)


@pytest.mark.asyncio
async def test_text_in_the_graph_never_reaches_the_sql(conn):
    hostile = "x'; DROP TABLE student; --"
    text = FULL.replace('* @queryDetail: counsellor_for_students', f'* @queryDetail: "{hostile}"')
    text = text.replace('# gpa [@Property]\n', '# gpa [@Property]\n* @column: "gpa; DROP TABLE student"\n')
    full, p = await projected(conn, text)
    bare = read(text.replace('* counselledBy -> adat\n', '').replace('* gpa: 3.4\n', '')).graph
    view = await augment(bare, registry=registry(p), conn=conn)  # the detail is handed over, never run
    assert held(view, 'chuks', GPA) == ['3.4']  # a column name that is not plain SQL is quoted, not obeyed
    assert conn.execute("SELECT count(*) FROM student").fetchone() == (2,)
    wrong = BARE.replace('* @table: student', '* @table: "student; DROP TABLE student"')
    with pytest.raises(CircumError, match='declares @table'):
        await augment(read(wrong).graph, registry=registry(p), conn=conn)
    assert conn.execute("SELECT count(*) FROM student").fetchone() == (2,)


@pytest.mark.asyncio
async def test_a_label_shared_by_several_tables_is_left_to_the_application(conn):
    _, p = await projected(conn)
    reg = registry(p)  # `name` is a column of both student and person
    with pytest.raises(CircumError, match=r"several tables \['person', 'student'\]"):
        await reg.resolvers[NAME]([NS + 'chuks'], ctx(NAME, conn=conn))
    assert NAME in reg.writers and CIRCUM[0] in reg.writers
