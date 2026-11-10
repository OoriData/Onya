# -*- coding: utf-8 -*-
# test/store/test_store_version.py
'''
``VersionedStore``: a change token per named graph, so a cache in another process can ask "has it changed?"
without fetching the graph. Runs against every backend through the shared ``store`` fixture.

    pytest -s test/store/test_store_version.py
'''

import asyncio
import sqlite3

import pytest

from onya.store import VersionedStore, connect
from onya.store.sync import connect as sync_connect
from store_helpers import DOCHEADER, NAME, parse

A = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
B = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n\n# Ify [Person]\n\n* age: 31\n'
OTHER = 'http://e.o/other'
OTHER_DOC = DOCHEADER.replace('http://e.o/doc', OTHER) + '\n# Ada [Person]\n\n* age: 36\n'


async def test_every_builtin_backend_is_versioned(store):
    assert isinstance(store, VersionedStore)


async def test_a_write_changes_the_token_and_a_read_does_not(store):
    await store.put(NAME, parse(A))
    v1 = await store.version(NAME)
    await store.get(NAME)
    assert await store.version(NAME) == v1  # reads leave it alone
    await asyncio.sleep(0.01)  # a file store's token includes a timestamp: keep writes apart
    await store.put(NAME, parse(B))
    v2 = await store.version(NAME)
    assert v2 != v1
    await asyncio.sleep(0.01)
    await store.put(NAME, parse(A), merge=False)  # a replacement is a write too
    assert await store.version(NAME) not in (v1, v2)  # and a token is never one seen before


async def test_a_graph_dropped_and_made_again_does_not_reuse_a_token(store):
    await store.put(NAME, parse(A))
    seen = {await store.version(NAME)}
    await store.drop(NAME)
    with pytest.raises(KeyError):
        await store.version(NAME)
    await asyncio.sleep(0.01)
    await store.put(NAME, parse(A))  # the very same content
    assert await store.version(NAME) not in seen


async def test_version_of_a_missing_graph_is_a_keyerror(store):
    with pytest.raises(KeyError):
        await store.version('http://e.o/nothing')


async def test_assertion_level_writes_change_the_token(store, backend):
    if backend == 'file':
        pytest.skip('the file backend has no assertion-level writes')
    await store.put(NAME, parse(A))
    v1 = await store.version(NAME)
    await store.add(NAME, 'http://e.o/Chuks', 'http://e.o/nickname', 'CK', kind='P')
    v2 = await store.version(NAME)
    assert v2 != v1
    await store.remove(NAME, 'http://e.o/Chuks', 'http://e.o/nickname', 'CK', kind='P')
    assert await store.version(NAME) not in (v1, v2)


async def test_versions_covers_several_graphs_and_a_name_with_no_graph_yet(store):
    await store.put(NAME, parse(A))
    both = [NAME, OTHER]
    before = await store.versions(both)  # OTHER does not exist yet: that is a state, not an error
    assert before == await store.versions(list(reversed(both)))  # the order of the names doesn't matter
    await store.put(OTHER, parse(OTHER_DOC))
    after = await store.versions(both)
    assert after != before  # the missing graph appearing
    await store.put(OTHER, parse(OTHER_DOC.replace('36', '37')), merge=False)
    assert await store.versions(both) != after  # a change to either
    await store.put(NAME, parse(B))
    assert await store.versions([OTHER]) == await store.versions([OTHER])  # unrelated to the other graph's writes


async def test_a_write_by_another_connection_is_seen(tmp_path):
    '''The point of the token: a second process asks the store, not its own memory.'''
    for url in (f'sqlite:{tmp_path}/app.db', f'file:{tmp_path}/graphs'):
        async with await connect(url) as reader, await connect(url) as writer:
            await writer.put(NAME, parse(A))
            v1 = await reader.version(NAME)
            await asyncio.sleep(0.01)
            await writer.put(NAME, parse(B))
            assert await reader.version(NAME) != v1, url


async def test_a_store_made_before_revisions_gets_the_table_and_reads_zero_until_written(tmp_path):
    path = tmp_path / 'old.db'
    async with await connect(f'sqlite:{path}') as st:
        await st.put(NAME, parse(A))
    with sqlite3.connect(path) as c:  # what a 0.6.1 database looks like: the graph, no revision table
        c.execute('DROP TABLE onya_graph_rev')
    async with await connect(f'sqlite:{path}') as st:
        assert await st.version(NAME) == '0'
        await st.put(NAME, parse(B))
        assert await st.version(NAME) != '0'


def test_sync_facade_has_the_token_where_the_store_does(tmp_path):
    with sync_connect(f'sqlite:{tmp_path}/app.db') as st:
        st.put(NAME, parse(A))
        v = st.version(NAME)
        assert isinstance(st.versions([NAME, OTHER]), str)
        st.put(NAME, parse(B))
        assert st.version(NAME) != v
