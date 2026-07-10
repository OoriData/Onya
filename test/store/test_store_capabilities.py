# -*- coding: utf-8 -*-
# test/store/test_store_capabilities.py
'''
Capability discovery via ``isinstance`` matches the table in the architecture doc: every
backend is a ``GraphStore``; the filesystem backend is *not* an ``AssertionStore`` (that
would be a lie — the file must be parsed whole); SQLite is an ``AssertionStore`` but not a
``GraphQueryStore``.

    pytest -s test/store/test_store_capabilities.py
'''

from onya.store import AssertionStore, GraphQueryStore, GraphStore, connect


async def test_filesystem_capabilities(tmp_path):
    async with await connect(f'file:{tmp_path}/graphs') as store:
        assert isinstance(store, GraphStore)
        assert not isinstance(store, AssertionStore)   # would be a lie for a whole-file backend
        assert not isinstance(store, GraphQueryStore)


async def test_sqlite_capabilities(tmp_path):
    async with await connect(f'sqlite:{tmp_path}/app.db') as store:
        assert isinstance(store, GraphStore)
        assert isinstance(store, AssertionStore)
        assert not isinstance(store, GraphQueryStore)   # PGQ is PostgreSQL >= 19 only
