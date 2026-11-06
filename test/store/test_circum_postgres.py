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
