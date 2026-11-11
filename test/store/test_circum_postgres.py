# -*- coding: utf-8 -*-
# test/store/test_circum_postgres.py
'''
`onya.circum` against a real PostgreSQL, through asyncpg. Runs only when ``ONYA_TEST_PG_DSN`` is set
(the same switch as the store suite); the SQLite tests in `test/test_circum.py` cover everything else.
'''

import os

import pytest

from onya.circum import from_shapes, last_run, materialize, statements
from onya.digest import digest
from onya.graph import graph
from onya.serial.literate import read

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.environ.get('ONYA_TEST_PG_DSN'), reason='ONYA_TEST_PG_DSN not set')]

TEXT = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
* @ordered: line

# Company [@Class]
# Person [@Class]
# name [@Property]
* @appliesTo -> Person
* @appliesTo -> Company
* @cardinality: 1
# visits [@Property]
* @appliesTo -> Person
* @as: integer
# seen [@Property]
* @appliesTo -> Person
* @as: datetime
# employer [@Property]
* @appliesTo -> Person
* @range -> Company
# line [@Property]
* @appliesTo -> Person
* @cardinality: 0..*
* @ordered: true

# acme [Company]
* name: Acme Ltd
# chuks [Person]
* name: Chuks
* visits: VISITS
* seen: 2026-03-02T09:30:00+02:00
* employer -> acme
* line: 14 Marina Rd
* line: Lagos
'''


def load(visits='7'):
    g = graph()
    read(TEXT.replace('VISITS', visits), g)
    return g


async def _drop(dsn, p):
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        for t in reversed([t.name for t in p.ordered_tables()]):
            await conn.execute(f'DROP TABLE IF EXISTS {t} CASCADE')
        await conn.execute('DROP TABLE IF EXISTS onya_circum_runs')
    finally:
        await conn.close()


async def test_materialize_is_idempotent_and_records_the_digest():
    dsn = os.environ['ONYA_TEST_PG_DSN']
    g = load()
    p = from_shapes(g, 'http://e.o/Person')
    await _drop(dsn, p)
    try:
        first = await materialize(dsn, p, g)
        assert (first.created, first.inserted) == (3, 4)
        second = await materialize(dsn, p, g)
        assert (second.inserted, second.updated, second.deleted, second.unchanged) == (0, 0, 0, 4)
        assert (await last_run(dsn, p))['graph_digest'] == digest(g)
        assert (await materialize(dsn, p, load('8'))).updated == 1
    finally:
        await _drop(dsn, p)


def test_postgres_ddl_statements():
    p = from_shapes(load(), 'http://e.o/Person')
    assert all(s.startswith('CREATE TABLE') for s in statements(p, 'postgres'))


async def test_into_the_stores_own_database():
    from onya.store import connect
    dsn = os.environ['ONYA_TEST_PG_DSN']
    g = load()
    p = from_shapes(g, 'http://e.o/Person')
    await _drop(dsn, p)
    try:
        async with await connect(dsn) as store:
            assert (await materialize(store, p, g)).inserted == 4
            assert (await materialize(store, p, load('9'))).updated == 1
            assert (await last_run(store, p))['unchanged'] == 3
    finally:
        await _drop(dsn, p)


# --- the read side, through asyncpg: a batch resolver using ANY($1), and an idempotent writer ---------------

SIDECAR = '''# @docheader
* @document: http://e.o/sidecar
* @nodebase: http://e.o/
* @schema: http://e.o/

# Student [@Class]
# Person [@Class]
# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @cardinality: 1
* @circumQuery -> counsellor-assignments
# counsellor-assignments [@Sidecar]
* @table: pg_counsellor
# chuks [Student]
# dede [Student]
'''


@pytest.mark.asyncio
async def test_augment_and_emit_through_asyncpg():
    import asyncpg
    from onya.circum import Edge, Node, Registry, augment, emit, strip

    label = 'http://e.o/counselledBy'
    conn = await asyncpg.connect(os.environ['ONYA_TEST_PG_DSN'])
    try:
        await conn.execute('DROP TABLE IF EXISTS pg_counsellor')
        await conn.execute('CREATE TABLE pg_counsellor (iri text PRIMARY KEY, counsellor text, name text)')
        await conn.execute("INSERT INTO pg_counsellor VALUES ('http://e.o/chuks', 'http://e.o/adat', 'Adat Okon')")
        calls = []
        reg = Registry()

        @reg.resolver(label)
        async def counselled_by(subjects, ctx):
            calls.append(list(subjects))
            rows = await ctx.conn.fetch('SELECT iri, counsellor, name FROM pg_counsellor WHERE iri = ANY($1)', subjects)
            return {r['iri']: [Edge(r['counsellor'], node=Node(('Person',), {'http://e.o/name': r['name']}))]
                    for r in rows}

        @reg.writer(label)
        async def put(rows, ctx):
            await ctx.conn.executemany(
                'INSERT INTO pg_counsellor (iri, counsellor) VALUES ($1, $2) '
                'ON CONFLICT (iri) DO UPDATE SET counsellor = excluded.counsellor',
                [(s, e.target) for s, items in rows.items() for e in items])

        g = read(SIDECAR).graph
        view = await augment(g, registry=reg, conn=conn)
        assert calls == [['http://e.o/chuks', 'http://e.o/dede']]  # one batch
        assert [str(e.target.id) for e in view['http://e.o/chuks'].getedge(label)] == ['http://e.o/adat']
        assert digest(strip(view)) == digest(g)

        g['http://e.o/dede'].add_edge(label, g.node('http://e.o/adat'))
        assert len((await emit(g, ['http://e.o/dede'], registry=reg, conn=conn)).moved) == 1
        assert not list(g['http://e.o/dede'].getedge(label))
        assert (await conn.fetchval("SELECT counsellor FROM pg_counsellor WHERE iri = 'http://e.o/dede'")
                ) == 'http://e.o/adat'
    finally:
        await conn.execute('DROP TABLE IF EXISTS pg_counsellor')
        await conn.close()


# --- tables as sidecars: resolvers and writers derived from a projection, over asyncpg -----------------------

TABLES = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# Student [@Class]
# Person [@Class]
# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @circumQuery -> students-db
# gpa [@Property]
* @appliesTo -> Student
* @as: number
* @circumQuery -> students-db
# seen [@Property]
* @appliesTo -> Student
* @as: datetime
* @circumQuery -> students-db
# interest [@Property]
* @appliesTo -> Student
* @cardinality: 0..*
* @circumQuery -> students-db
# students-db [@Sidecar]
* @table: student
# adat [Person]
# chuks [Student]
CHUKS
# dede [Student]
'''
CHUKS = '''* counselledBy -> adat
* gpa: 3.40
* seen: 2026-03-02T09:30:00+02:00
* interest: chess
* interest: music'''


@pytest.mark.asyncio
async def test_table_resolvers_and_writers_through_asyncpg():
    import asyncpg
    from onya.circum import CircumError, Registry, augment, emit, strip, table_resolvers, table_writers
    dsn = os.environ['ONYA_TEST_PG_DSN']
    full = read(TABLES.replace('CHUKS', CHUKS)).graph
    bare = lambda: read(TABLES.replace('CHUKS', '')).graph  # noqa: E731
    p = from_shapes(full, 'http://e.o/Student', array_columns=True)  # `interest` is a text[] column
    reg = Registry()
    reg.resolvers.update(table_resolvers(p))
    reg.writers.update(table_writers(p))
    await _drop(dsn, p)
    pool = await asyncpg.create_pool(dsn)

    def held(g, node, label):
        n = g['http://e.o/' + node]
        return sorted([a.value for a in n.getprop('http://e.o/' + label)]
                      + [str(e.target.id) for e in n.getedge('http://e.o/' + label)])
    try:
        await materialize(pool, p, full)
        view = await augment(bare(), registry=reg, conn=pool)
        assert held(view, 'chuks', 'counselledBy') == ['http://e.o/adat']
        assert held(view, 'chuks', 'gpa') == ['3.40']  # numeric keeps its scale
        assert held(view, 'chuks', 'interest') == ['chess', 'music']
        (seen,) = held(view, 'chuks', 'seen')
        assert seen == '2026-03-02T07:30:00Z'  # timestamptz comes back in UTC
        assert digest(strip(view)) == digest(bare())

        g = bare()
        g['http://e.o/dede'].add_property('http://e.o/gpa', '3.9')
        g['http://e.o/dede'].add_property('http://e.o/interest', 'reading')
        g['http://e.o/dede'].add_edge('http://e.o/counselledBy', g['http://e.o/adat'])
        assert len((await emit(g, ['http://e.o/dede'], registry=reg, conn=pool)).moved) == 3
        async with pool.acquire() as c:
            before = await c.fetchrow("SELECT * FROM student WHERE id = 'http://e.o/dede'")
        g = bare()
        g['http://e.o/dede'].add_property('http://e.o/gpa', '3.9')
        await emit(g, ['http://e.o/dede'], registry=reg, conn=pool)  # again: nothing to change
        async with pool.acquire() as c:
            assert await c.fetchrow("SELECT * FROM student WHERE id = 'http://e.o/dede'") == before
            await c.execute('ALTER TABLE student DROP COLUMN updated')
        with pytest.raises(CircumError, match="missing \\['updated'\\]"):
            await augment(bare(), registry=reg, conn=pool)
    finally:
        await pool.close()
        await _drop(dsn, p)


LEDGER = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

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
* @table: person
# adat [Person]
BODY
'''
Q1, Q2, HOURLY = ('* compensation: 5000\n  * period: 2026-Q1\n  * unit: month\n',
                  '* compensation: 5000\n  * period: 2026-Q2\n  * unit: month\n',
                  '* compensation: 60\n  * unit: hour\n')


@pytest.mark.asyncio
async def test_a_qualified_ledger_through_asyncpg():
    import asyncpg
    from onya.circum import CircumError, Registry, augment, emit, strip, table_resolvers, table_writers
    dsn = os.environ['ONYA_TEST_PG_DSN']
    graph_of = lambda body: read(LEDGER.replace('BODY', body)).graph  # noqa: E731
    p = from_shapes(graph_of(Q1 + Q2 + HOURLY), 'http://e.o/Person')
    reg = Registry()
    reg.resolvers.update(table_resolvers(p))
    reg.writers.update(table_writers(p))
    await _drop(dsn, p)
    pool = await asyncpg.create_pool(dsn)
    stored = ("SELECT value::text, period, unit FROM person_compensation WHERE person_id = 'http://e.o/adat' "
              'ORDER BY period')
    try:
        g = graph_of(Q1 + Q2 + HOURLY)
        await _setup(pool, p, graph_of(''))
        assert len((await emit(g, registry=reg, conn=pool)).moved) == 3
        async with pool.acquire() as c:
            assert [tuple(r) for r in await c.fetch(stored)] == [('60', '', 'hour'), ('5000', '2026-Q1', 'month'),
                                                               ('5000', '2026-Q2', 'month')]
        view = await augment(graph_of(''), registry=reg, conn=pool)
        assert sorted((a.value, tuple(c.value for c in a.getprop('http://e.o/period')))
                      for a in view['http://e.o/adat'].getprop('http://e.o/compensation')) == [
            ('5000', ('2026-Q1',)), ('5000', ('2026-Q2',)), ('60', ())]
        assert digest(strip(view)) == digest(graph_of(''))
        # a changed amount under an existing key is a conflict, and writes nothing
        changed = graph_of('* compensation: 5100\n  * period: 2026-Q1\n  * unit: month\n' + Q2.replace('Q2', 'Q3'))
        with pytest.raises(CircumError, match='for a person to decide'):
            await emit(changed, registry=reg, conn=pool)
        async with pool.acquire() as c:
            assert len(await c.fetch(stored)) == 3
    finally:
        await pool.close()
        await _drop(dsn, p)


async def _setup(pool, p, g):
    '''Create the projection's tables (empty graph), and give back the pool for `conn=`.'''
    await materialize(pool, p, g)
    return pool
