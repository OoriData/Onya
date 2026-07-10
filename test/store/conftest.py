# -*- coding: utf-8 -*-
# test/store/conftest.py
'''
Fixtures for the store conformance suite. One behavioral suite runs against every backend
via the parameterized ``store`` fixture: filesystem and SQLite always; PostgreSQL when
``ONYA_TEST_PG_DSN`` is set (its schema is reset between tests).
'''

import os

import pytest
import pytest_asyncio

from onya.store import connect


def _backends():
    backends = ['file', 'sqlite']
    if os.environ.get('ONYA_TEST_PG_DSN'):
        backends.append('postgres')
    return backends


def _url(backend, tmp_path):
    if backend == 'file':
        return f'file:{tmp_path}/graphs'
    if backend == 'sqlite':
        return f'sqlite:{tmp_path}/app.db'
    if backend == 'postgres':
        return os.environ['ONYA_TEST_PG_DSN']
    raise AssertionError(backend)


@pytest_asyncio.fixture(params=_backends())
async def store(request, tmp_path):
    '''An open store, one per (test, backend). PostgreSQL is reset to empty first.'''
    backend = request.param
    st = await connect(_url(backend, tmp_path))
    async with st:
        if backend == 'postgres' and hasattr(st, '_reset_for_tests'):
            await st._reset_for_tests()
        st.backend_label = backend  # for the odd test that needs to know
        yield st


@pytest.fixture
def backend(store):
    return getattr(store, 'backend_label', None)
