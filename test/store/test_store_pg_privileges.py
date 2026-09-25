# -*- coding: utf-8 -*-
# test/store/test_store_pg_privileges.py
'''
A least-privilege application role (data privileges only, no CREATE) can open a PostgreSQL
store someone else provisioned; when the schema is missing, it gets a clear ``StoreError``
naming what's missing. Gated on ``ONYA_TEST_PG_DSN``, which must connect as a role able to
create roles (e.g. the superuser a local container starts with). The temporary role and
schema are dropped afterwards.

    ONYA_TEST_PG_DSN=postgresql://... pytest -m integration test/store/test_store_pg_privileges.py
'''

import os
import secrets
from urllib.parse import urlsplit, urlunsplit

import pytest

from onya.serial import literate
from onya.store import connect
from onya.store.exceptions import StoreError

pytestmark = pytest.mark.integration

PG_DSN = os.environ.get('ONYA_TEST_PG_DSN')
NAME = 'http://example.org/graphs/priv'
DOC = '''# @docheader
* @nodebase: http://example.org/lib/
* @schema: https://schema.org/

# ada [Person]
* name: Ada Lovelace
'''


def _dsn_as(user: str, password: str, query: str = '') -> str:
    parts = urlsplit(PG_DSN)
    host = parts.hostname + (f':{parts.port}' if parts.port else '')
    return urlunsplit((parts.scheme, f'{user}:{password}@{host}', parts.path, query, ''))


@pytest.fixture
async def app_role():
    '''A LOGIN role with only USAGE + DML on the (already provisioned) public schema.'''
    if not PG_DSN:
        pytest.skip('ONYA_TEST_PG_DSN not set')
    asyncpg = pytest.importorskip('asyncpg')
    async with await connect(PG_DSN):  # make sure the schema exists (as the owner)
        pass
    role, pw = f'onya_app_{secrets.token_hex(4)}', secrets.token_hex(16)
    schema = f'{role}_empty'
    admin = await asyncpg.connect(PG_DSN)
    db = admin._params.database
    try:
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{pw}'")
        await admin.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {role}')
        await admin.execute(f'GRANT USAGE ON SCHEMA public TO {role}')
        await admin.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}')
        await admin.execute(f'CREATE SCHEMA {schema}')      # empty; the role may use but not create in it
        await admin.execute(f'GRANT USAGE ON SCHEMA {schema} TO {role}')
        yield role, pw, schema
    finally:
        await admin.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
        await admin.execute(f'DROP OWNED BY {role}')         # revokes its grants
        await admin.execute(f'DROP ROLE IF EXISTS {role}')
        await admin.close()


async def test_data_only_role_opens_provisioned_store(app_role):
    role, pw, _ = app_role
    async with await connect(_dsn_as(role, pw)) as st:
        assert st.has_trgm                                   # found the existing search objects
        await st.put(NAME, literate.read(DOC).graph)
        g = await st.get(NAME)
        assert g['http://example.org/lib/ada'].any_prop_value('schema:name') == 'Ada Lovelace'
        [hit] = await st.search(NAME, 'ada lovelac')
        assert hit.node_id == 'http://example.org/lib/ada'
        await st.drop(NAME)


async def test_data_only_role_gets_clear_error_when_schema_missing(app_role):
    role, pw, schema = app_role
    with pytest.raises(StoreError) as e:
        await connect(_dsn_as(role, pw, f'search_path={schema}'))  # an empty schema: nothing provisioned
    msg = str(e.value)
    assert 'missing: onya_meta, onya_graph' in msg
    assert 'may not create it' in msg and 'sql/examples/postgres-schema.sql' in msg
