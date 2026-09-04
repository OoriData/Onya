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
  materializing the whole graph) and ``OverlayReadStore`` (read-time union/scoped access
  across *multiple* named graphs, without disturbing per-graph storage);
- PostgreSQL >= 19 additionally satisfies ``GraphQueryStore`` (SQL/PGQ escape hatch).

``runtime_checkable`` only checks method *presence*, not signatures — which is exactly the
capability question we want to answer.
'''

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
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
              label: I | str | None = None, where: tuple[I | str, str, float | str] | None = None,
              ) -> AsyncIterator[tuple[I | str, I | str, str | I, dict]]:
        '''
        Stream assertions matching the constraints (``None`` means unconstrained).

        ``where`` is an optional single comparison against one *nested* property of the
        matched assertion: ``(label, op, value)`` with ``op`` one of ``'==' '!=' '<' '<='
        '>' '>='``, e.g. ``where=(ONYA_CONFIDENCE_REL, '>', 0.8)`` -- "edges labeled X whose
        nested @confidence > 0.8" -- without loading the graph. Deliberately narrow: a
        single comparison, not a general filter language, consistent with this store
        layer's stance that ``GraphQueryStore`` is the escape hatch for anything richer, not
        a query language Onya wraps. ``value`` compares numerically when both sides parse as
        a number, else as a string (only meaningful for ``'=='``/``'!='``).
        '''
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
class OverlayReadStore(Protocol):
    '''
    Read-only combination of multiple named graphs, without disturbing per-graph storage --
    the read-time counterpart to write-time ``put(merge=True)``, for callers who want to
    keep one named graph per source (clean per-source re-serialization, diffing, ``drop()``)
    but read a combined view across a chosen subset. Reproduces SPEC merge Rules 1-3
    exactly as ``graph.union()`` would (see ``onya.store._relational.build_union``), not a
    bare concatenation of rows across the selected graphs.

    Filesystem: not offered -- no pushdown is possible there (a Literate file must be parsed
    whole anyway; see ``AssertionStore``'s identical non-support). Compose ``get()`` +
    ``graph.union()`` instead:

        g = await store.get(names[0])
        for n in names[1:]:
            g.union(await store.get(n))

    SQLite/Postgres: offered, via genuine ``WHERE graph_pk IN (...)`` pushdown rather than
    ``len(names)`` separate round trips.

    ``overlay()`` (ordered-precedence shadowing on conflicts, as an alternative to raising)
    is deliberately not part of this protocol -- it needs its own design pass. See
    doc/design-persistence-architecture.md § Deferred / open questions.
    '''

    async def union(self, names: Sequence[I | str]) -> graph:
        '''
        Fully materialized merged view of the named graphs. Raises ``GraphMergeError`` on a
        genuine Rule 1 conflict between two of the named graphs (no lenient mode in this
        protocol version); ``KeyError`` if any name is absent; ``ValueError`` if ``names``
        is empty.
        '''
        ...

    def match_across(self, names: Sequence[I | str], origin: I | str | None = None,
                     label: I | str | None = None, where: tuple[I | str, str, float | str] | None = None,
                     ) -> AsyncIterator[tuple[I | str, I | str, str | I, dict]]:
        '''``AssertionStore.match``, scoped to the union of the named graphs.'''
        ...

    async def subgraph_across(self, names: Sequence[I | str], roots: set[I | str],
                              hops: int = 1) -> graph:
        '''``AssertionStore.subgraph``, scoped to the union of the named graphs.'''
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
