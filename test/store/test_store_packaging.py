# -*- coding: utf-8 -*-
# test/store/test_store_packaging.py
'''
The store backend entry points are registered under the *installed* (`onya.store.*`) names.
Because this repo maps ``pylib`` -> ``onya`` only during wheel building, this is meaningful
only against a real install (``uv pip install -U .``), never an editable one — which is the
project's rule anyway.

    pytest -s test/store/test_store_packaging.py
'''

from importlib.metadata import entry_points


def test_backend_entry_points_use_installed_names():
    eps = {ep.name: ep.value for ep in entry_points(group='onya.store.backends')}
    assert eps == {
        'file': 'onya.store.filesystem:FileStore',
        'sqlite': 'onya.store.sqlite:SqliteStore',
        'postgresql': 'onya.store.postgres:PostgresStore',
    }
    # object references must be the remapped onya.store.* names, never pylib.*
    assert all(v.startswith('onya.store.') for v in eps.values())
