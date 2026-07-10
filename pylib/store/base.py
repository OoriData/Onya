# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.base
'''
Store capability protocols.

Backends differ in power, so rather than one fat interface studded with
``NotImplementedError`` landmines we define a minimal base protocol plus optional
capability protocols, all ``runtime_checkable`` so callers can discover what a given store
can do with ``isinstance`` (see doc/design-persistence-architecture.md § The store
abstraction):

- every backend satisfies ``GraphStore`` (named whole graphs, checkpoint-style);
- the SQL backends additionally satisfy ``AssertionStore`` (fine-grained access without
  materializing the whole graph);
- PostgreSQL >= 19 additionally satisfies ``GraphQueryStore`` (SQL/PGQ escape hatch).

``runtime_checkable`` only checks method *presence*, not signatures — which is exactly the
capability question we want to answer.
'''

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from amara.iri import I

from onya.graph import graph


@runtime_checkable
class GraphStore(Protocol):
    '''
    The floor every backend meets: named whole graphs. Graph names are IRIs, aligning with
    the ``@document`` in a graph's own docheader; one store holds many named graphs.
    '''

    async def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        '''
        Persist ``g`` under ``name``. ``merge=True`` (default) unions with any stored graph
        per the SPEC merge rules (see ``onya.graph.graph.union``); ``merge=False`` replaces
        wholesale.
        '''
        ...

    async def get(self, name: I | str) -> graph:
        '''Load the named graph, fully materialized. ``KeyError`` if absent.'''
        ...

    async def drop(self, name: I | str) -> None:
        '''Remove the named graph. ``KeyError`` if absent.'''
        ...

    def names(self) -> AsyncIterator[I | str]:
        '''Async-iterate the names of the graphs this store holds.'''
        ...

    async def __aenter__(self) -> 'GraphStore': ...
    async def __aexit__(self, *exc) -> None: ...


@runtime_checkable
class AssertionStore(Protocol):
    '''
    Fine-grained access without materializing the whole graph. ``match`` mirrors
    ``graph.match()`` — the ``(origin, relation, target, annotations)`` tuple — so code
    written against the in-memory API ports by adding ``await`` / ``async for``.
    '''

    def match(self, name: I | str, origin: I | str | None = None,
              label: I | str | None = None,
              ) -> AsyncIterator[tuple[I | str, I | str, str | I, dict]]:
        '''Stream assertions matching the constraints (``None`` means unconstrained).'''
        ...

    async def subgraph(self, name: I | str, roots: set[I | str], hops: int = 1) -> graph:
        '''Materialize only the neighborhood of the given node ids, out to ``hops`` edges.'''
        ...

    async def add(self, name: I | str, origin: I | str, label: I | str, target_or_value,
                  *, kind: str, interp: I | str | None = None, id_: I | str | None = None) -> None:
        '''Add a single assertion (``kind`` is ``'E'`` for an edge, ``'P'`` for a property).'''
        ...

    async def remove(self, name: I | str, origin: I | str, label: I | str, target_or_value,
                     *, kind: str) -> None:
        '''Remove a single assertion matching the given skeleton.'''
        ...


@runtime_checkable
class GraphQueryStore(Protocol):
    '''
    PostgreSQL >= 19 SQL/PGQ escape hatch. Onya does not wrap PGQ in its own query
    language; it hands the user SQL against the store's property graph definitions plus the
    curated schema documentation (see doc/design-persistence-architecture.md § SQL/PGQ).
    '''

    async def graph_table(self, sql: str, *args) -> list[tuple]:
        '''Execute a query containing ``GRAPH_TABLE(...)`` against this store's PGQ graphs.'''
        ...
