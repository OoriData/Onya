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
from onya.store import AssertionStore, OverlayReadStore, connect as _async_connect


class SyncStore:
    '''
    Blocking wrapper around an already-open async store. Mirrors ``GraphStore`` with plain
    (non-``async``) methods; every streamed/generator call (``names``, ``match``,
    ``match_across``) returns a materialized list rather than an iterator.

    ``AssertionStore``/``OverlayReadStore`` methods are wired in only when the wrapped store
    actually satisfies that capability — mirroring the async layer's own "capabilities over
    inheritance" stance rather than raising ``NotImplementedError`` for absent ones. This
    means ``isinstance(sync_store, AssertionStore)`` (etc.) reports the same capability the
    async store itself has: the check is attribute presence (`typing.runtime_checkable`), and
    these methods are bound as instance attributes in ``__init__``, present only when earned.
    '''
    def __init__(self, store):
        self._store = store
        if isinstance(store, AssertionStore):
            self.match = self._match
            self.subgraph = self._subgraph
            self.add = self._add
            self.remove = self._remove
        if isinstance(store, OverlayReadStore):
            self.union = self._union
            self.match_across = self._match_across
            self.subgraph_across = self._subgraph_across
            self.overlay = self._overlay

    # --- GraphStore -----------------------------------------------------------------

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

    # --- AssertionStore (bound in __init__ only when the store offers it) -----------

    def _match(self, name: I | str, origin: I | str | None = None, label: I | str | None = None,
              where=None) -> list:
        async def _collect():
            return [r async for r in self._store.match(name, origin, label, where)]
        return asyncio.run(_collect())

    def _subgraph(self, name: I | str, roots: set[I | str], hops: int = 1) -> graph:
        return asyncio.run(self._store.subgraph(name, roots, hops))

    def _add(self, name: I | str, origin: I | str, label: I | str, target_or_value,
             *, kind: str, interp: I | str | None = None, id_: I | str | None = None) -> None:
        asyncio.run(self._store.add(name, origin, label, target_or_value,
                                    kind=kind, interp=interp, id_=id_))

    def _remove(self, name: I | str, origin: I | str, label: I | str, target_or_value,
               *, kind: str) -> None:
        asyncio.run(self._store.remove(name, origin, label, target_or_value, kind=kind))

    # --- OverlayReadStore (bound in __init__ only when the store offers it) ---------

    def _union(self, names) -> graph:
        return asyncio.run(self._store.union(names))

    def _match_across(self, names, origin: I | str | None = None, label: I | str | None = None,
                      where=None) -> list:
        async def _collect():
            return [r async for r in self._store.match_across(names, origin, label, where)]
        return asyncio.run(_collect())

    def _subgraph_across(self, names, roots: set[I | str], hops: int = 1) -> graph:
        return asyncio.run(self._store.subgraph_across(names, roots, hops))

    def _overlay(self, names, *, single_cardinality=frozenset(), key=None,
                precedence=None, prefer_confidence: bool = False):
        return asyncio.run(self._store.overlay(
            names, single_cardinality=single_cardinality, key=key,
            precedence=precedence, prefer_confidence=prefer_confidence))


@contextmanager
def connect(url: str):
    '''Open ``url`` and yield a blocking ``SyncStore``, closing it on exit.'''
    store = asyncio.run(_async_connect(url))
    asyncio.run(store.__aenter__())
    try:
        yield SyncStore(store)
    finally:
        asyncio.run(store.__aexit__(None, None, None))
