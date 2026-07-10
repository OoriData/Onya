# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.sync
'''
Minimal synchronous facade over the async store protocol, for scripts and REPL use.

This is a convenience only — not a second protocol and not backend-specific. Each call runs
the underlying coroutine with ``asyncio.run`` and the ``connect`` context manager drives the
store's async lifecycle. Because every call spins its own event loop, this facade suits the
loop-per-call backends (``file:``, ``sqlite:``); an asyncpg pool is bound to the loop that
created it, so the async API is the right choice for PostgreSQL under concurrency.

    from onya.store.sync import connect

    with connect('sqlite:app.db') as store:
        store.put('http://example.org/g', my_graph)
        g = store.get('http://example.org/g')
'''

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from amara.iri import I

from onya.graph import graph
from onya.store import connect as _async_connect


class SyncStore:
    '''
    Blocking wrapper around an already-open async store. Mirrors ``GraphStore`` with plain
    (non-``async``) methods; ``names()`` returns a materialized list rather than an iterator.
    '''
    def __init__(self, store):
        self._store = store

    def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        asyncio.run(self._store.put(name, g, merge=merge))

    def get(self, name: I | str) -> graph:
        return asyncio.run(self._store.get(name))

    def drop(self, name: I | str) -> None:
        asyncio.run(self._store.drop(name))

    def names(self) -> list:
        async def _collect():
            return [n async for n in self._store.names()]
        return asyncio.run(_collect())


@contextmanager
def connect(url: str):
    '''Open ``url`` and yield a blocking ``SyncStore``, closing it on exit.'''
    store = asyncio.run(_async_connect(url))
    asyncio.run(store.__aenter__())
    try:
        yield SyncStore(store)
    finally:
        asyncio.run(store.__aexit__(None, None, None))
