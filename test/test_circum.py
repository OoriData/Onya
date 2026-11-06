# -*- coding: utf-8 -*-
# test/test_circum.py
'''
The circum projection (`onya.circum`): graph -> relational tables, derived from shapes. SQLite only;
the PostgreSQL path is covered by the (opt-in) store test.

    pytest -s test/test_circum.py
'''

import sqlite3

import pytest

from onya.circum import (CircumError, Column, Projection, Table, ddl, from_shapes, last_run, materialize, rows,
                         single_valued)
from onya.digest import digest
from onya.graph import graph
from onya.serial.literate import read
from onya.shape import validate

HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
* @ordered: addressLine
'''

SHAPES = '''
# Company [@Class]
# Person [@Class]
# Student [@Class]
* @subClassOf -> Person

# name [@Property]
* @appliesTo -> Person
* @appliesTo -> Company
* @as: text
* @cardinality: 1

# registered [@Property]
* @appliesTo -> Person
* @as: datetime
* @cardinality: 0..1

# visits [@Property]
* @appliesTo -> Person
* @as: integer
* @cardinality: 0..1

# score [@Property]
* @appliesTo -> Person
* @as: number

# active [@Property]
* @appliesTo -> Person
* @as: boolean

# status [@Property]
* @appliesTo -> Person
* @oneOf: active
* @oneOf: suspended
* @cardinality: 1

# employer [@Property]
* @appliesTo -> Person
* @range -> Company
* @cardinality: 0..1

# hobby [@Property]
* @appliesTo -> Person
* @as: text
* @cardinality: 0..*

# addressLine [@Property]
* @appliesTo -> Person
* @as: text
* @cardinality: 0..*
* @ordered: true
'''

DATA = '''
# acme [Company]
* name: Acme Ltd

# chuks [Person]
* name: Chukwuemeka Okafor
* registered: 2026-03-02T09:30:00Z
* visits: 7
* score: 2.5
* active: true
* status: active
* employer -> acme
* hobby: chess
* hobby: running
* addressLine: 14 Marina Rd
* addressLine: Lagos

# ify [Student]
* name: Ify
* status: suspended
'''


def load(text=DATA, track=False):
    g = graph()
    read(HEAD + SHAPES + text, g, track_locations=track)
    return g


@pytest.fixture
def g():
    return load()


def test_projection_from_shapes(g):
    p = from_shapes(g, 'http://e.o/Person')
    assert [t.name for t in p.ordered_tables()][:2] == ['company', 'person']  # FK order, from the references
    person = next(t for t in p.tables if t.name == 'person')
    cols = {c.name: c for c in person.columns}
    assert cols['name'].type == 'text' and not cols['name'].nullable
    assert cols['registered'].type == 'timestamptz' and cols['registered'].nullable
    assert cols['visits'].type == 'integer' and cols['score'].type == 'numeric' and cols['active'].type == 'boolean'
    assert cols['employer_id'].ref == 'company' and cols['employer_id'].kind == 'edge'
    assert cols['status'].one_of == ('active', 'suspended')
    assert {t.name for t in p.tables} == {'company', 'person', 'person_hobby', 'person_address_line'}
    ordered = next(t for t in p.tables if t.name == 'person_address_line')
    assert [c.name for c in ordered.columns] == ['person_id', 'value', 'ordinal']
    assert ordered.key == ('person_id', 'ordinal')


def test_ddl_postgres_and_sqlite(g):
    p = from_shapes(g, 'http://e.o/Person')
    pg, lite = ddl(p), ddl(p, 'sqlite')
    assert pg.index('CREATE TABLE company') < pg.index('CREATE TABLE person ')
    assert 'registered timestamptz,' in pg and 'name text NOT NULL' in pg and 'visits integer,' in pg
    assert "CHECK (status IN ('active', 'suspended'))" in pg
    assert 'FOREIGN KEY (employer_id) REFERENCES company (id) DEFERRABLE INITIALLY DEFERRED' in pg
    assert 'PRIMARY KEY (person_id, ordinal)' in pg
    assert 'registered TEXT,' in lite and 'visits INTEGER,' in lite
    with pytest.raises(ValueError):
        ddl(p, 'oracle')


def test_unknown_or_absent_as_is_text_never_a_guess():
    # an @as the projection doesn't know, and no @as at all
    extra = HEAD + '''
# Thing [@Class]
# mood [@Property]
* @appliesTo -> Thing
* @as: http://e.o/mood
# note [@Property]
* @appliesTo -> Thing
'''
    h = graph()
    read(extra, h)
    t = from_shapes(h, 'http://e.o/Thing').tables[0]
    assert {c.name: c.type for c in t.columns[1:]} == {'mood': 'text', 'note': 'text'}


def test_rows_are_typed(g):
    p = from_shapes(g, 'http://e.o/Person')
    r = rows(p, g)
    assert r['company'] == [('http://e.o/acme', 'Acme Ltd')]
    chuks = next(x for x in r['person'] if x[0] == 'http://e.o/chuks')
    named = dict(zip([c.name for c in next(t for t in p.tables if t.name == 'person').columns], chuks))
    assert named['visits'] == 7 and isinstance(named['visits'], int)
    assert named['active'] is True and str(named['score']) == '2.5'
    assert named['registered'].isoformat() == '2026-03-02T09:30:00+00:00'
    assert named['employer_id'] == 'http://e.o/acme'
    assert r['person_hobby'] == [('http://e.o/chuks', 'chess'), ('http://e.o/chuks', 'running')]
    assert r['person_address_line'] == [('http://e.o/chuks', '14 Marina Rd', 1), ('http://e.o/chuks', 'Lagos', 2)]


def test_subclass_instances_are_in_the_superclass_table(g):
    r = rows(from_shapes(g, 'http://e.o/Person'), g)
    assert {x[0] for x in r['person']} == {'http://e.o/chuks', 'http://e.o/ify'}


def test_a_bad_value_names_the_node_and_the_line_and_all_problems():
    g = load(DATA + '''
# dede [Person]
* name: Dede
* status: active
* visits: seven
* score: lots
''', track=True)
    with pytest.raises(CircumError) as ei:
        rows(from_shapes(g, 'http://e.o/Person'), g)
    msgs = ei.value.problems
    assert len(msgs) == 2 and all('http://e.o/dede' in m for m in msgs)
    assert any('visits' in m and 'seven' in m and 'at ' in m for m in msgs)


def test_missing_required_and_too_many_values():
    g = load('''
# a [Person]
* status: active

# b [Person]
* name: B
* name: Bee
* status: active
''')
    with pytest.raises(CircumError) as ei:
        rows(from_shapes(g, 'http://e.o/Person'), g)
    text = ' | '.join(ei.value.problems)
    assert 'a: name: required' in text and 'b: name: 2 values' in text


def test_edge_to_a_node_that_is_in_no_table():
    g = load('''
# chuks [Person]
* name: Chuks
* status: active
* employer -> nowhere
''')
    with pytest.raises(CircumError, match='not in table company'):
        rows(from_shapes(g, 'http://e.o/Person'), g)


def test_ordering_problems_are_reported():
    g = load('''
# chuks [Person]
* name: Chuks
* status: active
* addressLine: one
  * @ordering: 1
* addressLine: two
  * @ordering: 1
''')
    with pytest.raises(CircumError, match='share @ordering'):
        rows(from_shapes(g, 'http://e.o/Person'), g)


def test_table_and_column_overrides():
    g = graph()
    read(HEAD + '''
# Thing [@Class]
* @table: widgets
# fooBar [@Property]
* @appliesTo -> Thing
* @column: fb
* @as: integer
''', g)
    t = from_shapes(g, 'http://e.o/Thing').tables[0]
    assert t.name == 'widgets' and [c.name for c in t.columns] == ['id', 'fb']


def test_derived_column_name_collision_is_an_error():
    g = graph()
    read(HEAD + '''
# Thing [@Class]
# fooBar [@Property]
* @appliesTo -> Thing
# foo_bar [@Property]
* @appliesTo -> Thing
''', g)
    with pytest.raises(CircumError, match='@column'):
        from_shapes(g, 'http://e.o/Thing')


def test_reserved_word_names_are_quoted():
    g = graph()
    read(HEAD + '''
# Thing [@Class]
# order [@Property]
* @appliesTo -> Thing
''', g)
    assert 'CREATE TABLE thing (\n    id text NOT NULL,\n    "order" text' in ddl(from_shapes(g, 'http://e.o/Thing'))


def test_self_reference_and_cycles():
    g = graph()
    read(HEAD + '''
# Person [@Class]
# knows [@Property]
* @appliesTo -> Person
* @range -> Person
# a [Person]
* knows -> a
''', g)
    p = from_shapes(g, 'http://e.o/Person')  # a table may reference itself
    assert 'REFERENCES person (id)' in ddl(p)
    cyc = graph()
    read(HEAD + '''
# A [@Class]
# B [@Class]
# ab [@Property]
* @appliesTo -> A
* @range -> B
# ba [@Property]
* @appliesTo -> B
* @range -> A
''', cyc)
    with pytest.raises(CircumError, match='cycle'):
        ddl(from_shapes(cyc, 'http://e.o/A'))


def test_array_columns_need_postgres(g):
    p = from_shapes(g, 'http://e.o/Person', array_columns=True)
    assert 'hobby text[]' in ddl(p) and 'address_line text[]' in ddl(p)
    assert any(c.array for c in next(t for t in p.tables if t.name == 'person').columns)
    with pytest.raises(CircumError, match='arrays need PostgreSQL'):
        ddl(p, 'sqlite')
    r = rows(p, g)
    person = [c.name for c in next(t for t in p.tables if t.name == 'person').columns]
    chuks = next(x for x in r['person'] if x[0] == 'http://e.o/chuks')
    assert chuks[person.index('address_line')] == ['14 Marina Rd', 'Lagos']
    assert 'person_hobby' not in r


def test_hand_written_projection():
    g = graph()
    read(HEAD + '''
# a [Person]
* name: A
''', g)
    p = Projection([Table('people', 'http://e.o/Person', [Column('id', 'text', False, 'id'),
                                                          Column('full_name', 'text', True, 'value', 'http://e.o/name')])])
    assert rows(p, g) == {'people': [('http://e.o/a', 'A')]}


def test_single_valued():
    g = load()
    assert single_valued(g) == {'http://e.o/name', 'http://e.o/registered', 'http://e.o/visits', 'http://e.o/status',
                                'http://e.o/employer'}


# --- materialize ---------------------------------------------------------------------

def select(conn, sql):
    return conn.execute(sql).fetchall()


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    c.execute('PRAGMA foreign_keys=ON')
    yield c
    c.close()


async def test_materialize_then_idempotent(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    first = await materialize(conn, p, g)
    assert (first.created, first.inserted, first.updated, first.deleted) == (4, 7, 0, 0)
    assert select(conn, 'SELECT name, visits, active, employer_id FROM person ORDER BY id') == [
        ('Chukwuemeka Okafor', 7, 1, 'http://e.o/acme'), ('Ify', None, None, None)]
    assert select(conn, 'SELECT value, ordinal FROM person_address_line') == [('14 Marina Rd', 1), ('Lagos', 2)]
    assert select(conn, 'SELECT registered FROM person WHERE visits = 7') == [('2026-03-02T09:30:00+00:00',)]
    second = await materialize(conn, p, g)
    assert (second.created, second.inserted, second.updated, second.deleted, second.unchanged) == (0, 0, 0, 0, 7)


async def test_changes_are_updates_inserts_and_deletes(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    await materialize(conn, p, g)
    g2 = load(DATA.replace('visits: 7', 'visits: 8').replace('* hobby: chess\n', '').replace(
        '# ify [Student]', '# new [Person]\n* name: New\n* status: active\n\n# ify [Student]'))
    r = await materialize(conn, p, g2)
    assert (r.inserted, r.updated, r.deleted) == (1, 1, 1)  # new person; chuks visits; chess
    assert select(conn, 'SELECT visits FROM person WHERE id = "http://e.o/chuks"') == [(8,)]
    assert select(conn, 'SELECT value FROM person_hobby') == [('running',)]
    assert r.tables['person_hobby'] == (0, 0, 1, 1)


async def test_bad_value_writes_nothing(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    bad = load(DATA + '\n# dede [Person]\n* name: Dede\n* status: active\n* visits: seven\n')
    with pytest.raises(CircumError):
        await materialize(conn, p, bad)
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone() == (0,)


async def test_database_failure_rolls_back(g, conn):
    # status is NOT NULL: a node that lacks it is caught before writing; a node whose status breaks the CHECK
    # can't be, if the shape (and so the projection) leaves it out. The DB must then undo everything.
    p = from_shapes(g, 'http://e.o/Person')
    await materialize(conn, p, g)
    bad = load(DATA + '\n# zed [Person]\n* name: Zed\n* status: gone\n')
    with pytest.raises(sqlite3.IntegrityError):
        await materialize(conn, p, bad)
    assert select(conn, 'SELECT count(*) FROM person') == [(2,)]


async def test_provenance_records_the_graph_digest(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    assert await last_run(conn, p) is None
    r = await materialize(conn, p, g)
    run = await last_run(conn, p)
    assert run['graph_digest'] == r.graph_digest == digest(g)
    assert (run['inserted'], run['unchanged']) == (7, 0)
    await materialize(conn, p, g)
    assert (await last_run(conn, p))['unchanged'] == 7


async def test_digest_ignores_how_the_file_was_written(g, conn):
    h = graph()
    read(HEAD + DATA + SHAPES, h)  # same content, other order
    assert digest(h) == digest(g)


async def test_incremental_touches_only_the_named_nodes(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    await materialize(conn, p, g)
    g2 = load(DATA.replace('visits: 7', 'visits: 9').replace('name: Ify', 'name: Ifeoma'))
    r = await materialize(conn, p, g2, nodes=['http://e.o/chuks'])
    assert (r.inserted, r.updated, r.deleted) == (0, 1, 0)
    assert select(conn, 'SELECT name FROM person WHERE id = "http://e.o/ify"') == [('Ify',)]  # not re-projected
    assert r.graph_digest == digest(g2)  # still the whole graph's digest


async def test_incremental_removes_a_node_that_is_gone(g, conn):
    p = from_shapes(g, 'http://e.o/Person')
    await materialize(conn, p, g)
    g2 = load(DATA.replace('# ify [Student]\n* name: Ify\n* status: suspended\n', ''))
    r = await materialize(conn, p, g2, nodes=['http://e.o/ify'])
    assert r.deleted == 1 and select(conn, 'SELECT id FROM person') == [('http://e.o/chuks',)]


async def test_dates_are_utc_timestamps(conn):
    g = graph()
    read(HEAD + '''
# E [@Class]
# when [@Property]
* @appliesTo -> E
* @as: datetime
# a [E]
* when: 2026-03-02
# b [E]
* when: 2026-03-02T10:00:00+02:00
''', g)
    p = from_shapes(g, 'http://e.o/E')
    await materialize(conn, p, g)
    assert select(conn, 'SELECT id, "when" FROM e ORDER BY id') == [
        ('http://e.o/a', '2026-03-02T00:00:00+00:00'), ('http://e.o/b', '2026-03-02T08:00:00+00:00')]
    assert (await materialize(conn, p, g)).unchanged == 2


async def test_materialize_to_a_url(tmp_path, g):
    p = from_shapes(g, 'http://e.o/Person')
    url = f'sqlite:{tmp_path / "circ.db"}'
    assert (await materialize(url, p, g)).inserted == 7
    assert (await materialize(url, p, g)).unchanged == 7
    assert (await last_run(url, p))['projection'] == 'http://e.o/Person'


async def test_into_a_store_database(g, tmp_path):
    from onya.store import connect
    async with await connect(f'sqlite:{tmp_path / "app.db"}') as store:
        await store.put('http://e.o/graph/a', g)
        p = from_shapes(g, 'http://e.o/Person')
        assert (await materialize(store, p, await store.get('http://e.o/graph/a'))).inserted == 7


async def test_unknown_target():
    with pytest.raises(ValueError, match='scheme'):
        await materialize('mysql:x', Projection([]), graph())
    with pytest.raises(TypeError):
        await materialize(42, Projection([]), graph())


# --- authored and runtime graphs -----------------------------------------------------

async def test_authored_and_runtime_layers(tmp_path):
    from onya.store import connect
    authored = load()
    runtime = graph()
    read(HEAD + '\n# chuks [Person]\n* status: suspended\n', runtime)
    AUTH, RUN = 'http://e.o/graph/authored', 'http://e.o/graph/runtime'
    async with await connect(f'sqlite:{tmp_path / "app.db"}') as store:
        await store.put(AUTH, authored, merge=False)
        await store.put(RUN, runtime)
        # union keeps both values: that breaks the shape, and the projection refuses to pick one
        u = await store.union([AUTH, RUN])
        assert [f.kind for f in validate(u, shapes=u).errors] == ['cardinality']
        with pytest.raises(CircumError, match='2 values'):
            rows(from_shapes(u, 'http://e.o/Person'), u)
        # overlay lets the later layer win
        merged, shadowed = await store.overlay([AUTH, RUN], single_cardinality=single_valued(authored),
                                               precedence=[RUN, AUTH])
        assert len(shadowed) == 1
        assert not validate(merged, shapes=merged).errors
        p = from_shapes(merged, 'http://e.o/Person')
        c = sqlite3.connect(':memory:', check_same_thread=False)
        await materialize(c, p, merged)
        assert select(c, 'SELECT status FROM person WHERE id = "http://e.o/chuks"') == [('suspended',)]
        # re-importing the authored file leaves the runtime layer alone
        await store.put(AUTH, load(), merge=False)
        again, _ = await store.overlay([AUTH, RUN], single_cardinality=single_valued(authored), precedence=[RUN, AUTH])
        await materialize(c, p, again)
        assert select(c, 'SELECT status FROM person WHERE id = "http://e.o/chuks"') == [('suspended',)]


# --- CLI -----------------------------------------------------------------------------

def test_cli_project_prints_ddl_and_writes_tables(tmp_path, capsys):
    from onya.cli.onya import project
    f = tmp_path / 'data.onya'
    f.write_text(HEAD + SHAPES + DATA, encoding='utf-8')
    project(str(f), 'http://e.o/Person', dialect='sqlite')
    assert 'CREATE TABLE person (' in capsys.readouterr().out
    db = tmp_path / 'c.db'
    project(str(f), 'http://e.o/Person', to=f'sqlite:{db}')
    assert '7 rows inserted' in capsys.readouterr().out
    assert sqlite3.connect(db).execute('SELECT count(*) FROM person').fetchone() == (2,)


def test_cli_project_bad_value_exits_2_naming_the_line(tmp_path, capsys):
    from onya.cli.onya import project
    f = tmp_path / 'data.onya'
    f.write_text(HEAD + SHAPES + DATA + '\n# dede [Person]\n* name: Dede\n* status: active\n* visits: seven\n',
                 encoding='utf-8')
    db = tmp_path / 'c.db'
    with pytest.raises(SystemExit) as ei:
        project(str(f), 'http://e.o/Person', to=f'sqlite:{db}')
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert 'dede' in err and 'seven' in err and 'data.onya:' in err
    assert not db.exists() or sqlite3.connect(db).execute("SELECT count(*) FROM sqlite_master").fetchone() == (0,)
