# -*- coding: utf-8 -*-
# test/store/test_store_connect.py
'''
The ``connect`` factory's scheme dispatch and the synchronous facade.

    pytest -s test/store/test_store_connect.py
'''

import pytest

from onya.store import connect
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
