# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store
'''
Pluggable persistence for Onya graphs.

Three backends ship in this package, discovered by URL scheme through the
``onya.store.backends`` entry-point group:

- ``file:``        — one Onya Literate file per named graph (default; the testing fake).
- ``sqlite:``      — stdlib ``sqlite3``, zero added dependencies.
- ``postgresql://`` — asyncpg, extras-gated (``pip install "onya[postgres]"``), with
  SQL/PGQ property graph support enabled automatically on PostgreSQL >= 19.

The layer is a peripheral, not an organ: ``onya.store`` imports the core model, never the
reverse. A backend is *correct* exactly when a round trip through it is indistinguishable
from an in-memory graph union (``onya.graph.graph.union``).

    from onya.store import connect

    async with await connect('sqlite:app.db') as store:
        await store.put('http://example.org/g', my_graph)
        g = await store.get('http://example.org/g')
'''

from __future__ import annotations

from onya.graph import AssertionIdConflict, GraphMergeError

from onya.store.base import AssertionStore, GraphQueryStore, GraphStore
from onya.store.exceptions import StoreError, UnknownSchemaVersion

__all__ = [
    'connect',
    'GraphStore',
    'AssertionStore',
    'GraphQueryStore',
    'StoreError',
    'UnknownSchemaVersion',
    'AssertionIdConflict',
    'GraphMergeError',
]

# Built-in scheme -> (module, class) mapping. Entry points (added by installed distributions)
# take precedence; this fallback keeps ``connect`` working before/without entry-point
# metadata and documents the schemes this repo ships. Modules are imported lazily so that
# nothing (especially asyncpg, in the postgres backend) loads until its scheme is used.
_BUILTIN_BACKENDS: dict[str, tuple[str, str]] = {
    'file': ('onya.store.filesystem', 'FileStore'),
    'sqlite': ('onya.store.sqlite', 'SqliteStore'),
    'postgresql': ('onya.store.postgres', 'PostgresStore'),
    'postgres': ('onya.store.postgres', 'PostgresStore'),  # friendly alias for asyncpg users
}


def _scheme(url: str) -> str:
    scheme, sep, _ = url.partition(':')
    if not sep:
        raise ValueError(f'Store URL {url!r} has no scheme (expected e.g. "sqlite:app.db")')
    return scheme.lower()


def _entry_point_backends() -> dict[str, object]:
    '''Map scheme -> entry point for the ``onya.store.backends`` group (may be empty).'''
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group='onya.store.backends')
    except TypeError:  # pragma: no cover - very old importlib.metadata
        eps = entry_points().get('onya.store.backends', [])
    return {ep.name: ep for ep in eps}


def _resolve_backend(scheme: str):
    '''Return the backend class for ``scheme`` (entry points first, built-ins as fallback), or None.'''
    ep = _entry_point_backends().get(scheme)
    if ep is not None:
        return ep.load()
    target = _BUILTIN_BACKENDS.get(scheme)
    if target is None:
        return None
    import importlib
    module_name, attr = target
    return getattr(importlib.import_module(module_name), attr)


async def connect(url: str) -> GraphStore:
    '''
    Open a store for ``url``, dispatching on its scheme. Backends are loaded lazily, so the
    (extras-gated) PostgreSQL driver is imported only for a ``postgresql://`` URL. An
    unknown scheme raises ``ValueError`` naming the schemes this build knows.

    The returned store is already open; use it as an async context manager to close it::

        async with await connect('sqlite:app.db') as store:
            ...
    '''
    scheme = _scheme(url)
    cls = _resolve_backend(scheme)
    if cls is None:
        known = sorted(set(_BUILTIN_BACKENDS) | set(_entry_point_backends()))
        raise ValueError(f'Unknown store URL scheme {scheme!r}; known schemes: {known}')
    return await cls.from_url(url)
