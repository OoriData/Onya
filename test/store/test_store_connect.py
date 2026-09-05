# -*- coding: utf-8 -*-
# test/store/test_store_connect.py
'''
The ``connect`` factory's scheme dispatch and the synchronous facade.

    pytest -s test/store/test_store_connect.py
'''

import pytest

from onya.store import AssertionStore, OverlayReadStore, connect
from onya.store.sync import connect as sync_connect
from store_helpers import DOCHEADER, NAME, canon, parse


async def test_unknown_scheme_raises_valueerror():
    with pytest.raises(ValueError, match='scheme'):
        await connect('mysql://localhost/db')


async def test_missing_scheme_raises_valueerror():
    with pytest.raises(ValueError):
        await connect('/just/a/path')


def test_sync_facade_roundtrip(tmp_path):
    doc = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    with sync_connect(f'sqlite:{tmp_path}/app.db') as store:
        store.put(NAME, parse(doc))
        got = store.get(NAME)
        assert canon(got) == canon(parse(doc))
        assert NAME in {str(n) for n in store.names()}
        store.drop(NAME)
        assert NAME not in {str(n) for n in store.names()}


def test_sync_facade_file_backend(tmp_path):
    doc = DOCHEADER + '\n# Ada [Person]\n\n* age: 31\n'
    with sync_connect(f'file:{tmp_path}/graphs') as store:
        store.put(NAME, parse(doc))
        assert canon(store.get(NAME)) == canon(parse(doc))


def test_sync_facade_capability_discovery_matches_the_async_store(tmp_path):
    '''
    AssertionStore/OverlayReadStore methods are wired onto SyncStore only when the wrapped
    store actually offers them -- so isinstance() through the sync facade reports the same
    capability the async store itself has, not "every method always present."
    '''
    with sync_connect(f'sqlite:{tmp_path}/app.db') as sqlite_store:
        assert isinstance(sqlite_store, AssertionStore)
        assert isinstance(sqlite_store, OverlayReadStore)

    with sync_connect(f'file:{tmp_path}/graphs') as file_store:
        assert not isinstance(file_store, AssertionStore)
        assert not isinstance(file_store, OverlayReadStore)


def test_sync_facade_assertion_and_overlay_capabilities(tmp_path):
    doc_a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    with sync_connect(f'sqlite:{tmp_path}/app.db') as store:
        store.put(NAME, parse(doc_a))

        rows = store.match(NAME, 'http://e.o/Chuks')
        assert isinstance(rows, list)   # materialized, not an async iterator
        assert ('https://schema.org/age', '28') in [(str(r), str(t)) for _o, r, t, _ann in rows]

        sg = store.subgraph(NAME, {'http://e.o/Chuks'}, hops=1)
        assert 'http://e.o/Chuks' in sg.nodes

        store.add(NAME, 'http://e.o/Chuks', 'https://schema.org/email', 'c@example.org', kind='P')
        rows2 = store.match(NAME, 'http://e.o/Chuks', 'https://schema.org/email')
        assert [str(t) for _o, _r, t, _ann in rows2] == ['c@example.org']
        store.remove(NAME, 'http://e.o/Chuks', 'https://schema.org/email', 'c@example.org', kind='P')
        assert store.match(NAME, 'http://e.o/Chuks', 'https://schema.org/email') == []

        other_doc = DOCHEADER.replace('http://e.o/doc', 'http://e.o/doc2') + \
            '\n# Chuks [Person]\n\n* email: b@example.org\n'
        store.put('http://e.o/doc2', parse(other_doc))
        merged = store.union([NAME, 'http://e.o/doc2'])
        merged_chuks = merged['http://e.o/Chuks']
        assert {p.value for p in merged_chuks.properties if str(p.label) == 'https://schema.org/age'} == {'28'}

        rows3 = store.match_across([NAME, 'http://e.o/doc2'], label='https://schema.org/email')
        assert [str(t) for _o, _r, t, _ann in rows3] == ['b@example.org']

        sg2 = store.subgraph_across([NAME, 'http://e.o/doc2'], {'http://e.o/Chuks'}, hops=1)
        assert 'http://e.o/Chuks' in sg2.nodes

        g, conflicts = store.overlay([NAME, 'http://e.o/doc2'])
        assert conflicts == []   # no cardinality hints -> reduces to union() behavior
