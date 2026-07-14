# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.nx
'''
Project an Onya graph into networkx for analytics, and write results back as typed
assertions — extras-gated: ``pip install "onya[nx]"``.

networkx is imported **lazily inside** the functions, so neither importing this module nor
using another serializer requires it; its absence raises an instructive ``ImportError``. The
projection is an analytics peripheral in the same architectural sense as ``onya.store``: it
imports the core (``onya.graph``, ``onya.terms``, optionally ``onya.interp``); the core never
imports it.

The round trip — project, compute in networkx, write the results back — makes analytics
first-class Onya data: ``write_back`` records each result as a typed, merge-safe assertion
that survives ``store.put(name, g, merge=True)`` and is queryable via ``graph.select``
(see SPEC § Selecting assertions).

Example usage:
    import networkx
    from onya.graph import graph
    from onya.serial import nx
    from onya.terms import ONYA_INTERP

    g = graph()
    alice = g.node('http://example.org/Alice', 'http://schema.org/Person')
    bob = g.node('http://example.org/Bob', 'http://schema.org/Person')
    carol = g.node('http://example.org/Carol', 'http://schema.org/Person')
    alice.add_edge('http://schema.org/knows', bob)
    bob.add_edge('http://schema.org/knows', carol)

    mg = nx.to_networkx(g)                                   # a networkx.MultiDiGraph
    scores = networkx.betweenness_centrality(mg)            # compute anything networkx offers
    metric = 'http://example.org/analytics/betweenness'
    nx.write_back(g, metric, scores, interp=ONYA_INTERP('number'))  # results as typed assertions

    # The scores are now ordinary Onya properties, readable back through the graph:
    from onya.interp import value_of
    for p in g.select(label=metric):
        print(p.origin.id, value_of(p))                     # a Python number, via the contract

Loss policy (v1 — first-level structure only):
    - Onya node -> networkx node keyed by ``str(node.id)`` (the full IRI; compact for display
      with ``onya.util.compact_iri``). Node attributes: ``types`` = tuple of ``str`` type IRIs;
      each property -> an attribute keyed by ``str(label)`` holding a **list** of values
      (multi-valued properties stay honest lists, never last-wins). Full-IRI property keys
      cannot collide with the bare ``types`` key.
    - Onya edge -> networkx edge with an **auto-assigned key** (parallel edges stay distinct),
      ``label`` = ``str(edge.label)`` plus the edge's first-level properties as list-valued
      attributes. Edges are **not** keyed by label: that would silently collapse duplicate
      same-skeleton occurrences (an ambient merge). The projection reflects the graph **as it
      is** — call ``g.merge()`` first for a normalized projection.
    - An edge whose target is an identified assertion (``isinstance(edge.target, assertion)``)
      is **skipped** in v1 (a single aggregated warning reports the count). Nested assertions
      below the first level are dropped. A future ``projections=`` argument will let callers
      register patterns for flattening deeper nested structures.

The target is always a ``networkx.MultiDiGraph``. If you want parallel edges collapsed, wrap
the result: ``networkx.DiGraph(nx.to_networkx(g))``.
'''

from __future__ import annotations

import warnings

from onya.graph import graph, assertion

__all__ = ['to_networkx', 'write_back']

_IMPORT_HINT = 'networkx projection requires: pip install "onya[nx]"'


def _networkx():
    '''Lazy, extras-gated import of networkx, with an instructive error when absent.'''
    try:
        import networkx
    except ImportError as e:  # feature-detected, not silently degraded
        raise ImportError(_IMPORT_HINT) from e
    return networkx


def _default_registry(registry):
    '''Resolve ``registry=None`` to ``onya.interp.DEFAULT``, imported only when needed so the
    default (raw-string) path adds no import weight.'''
    if registry is not None:
        return registry
    from onya.interp import DEFAULT
    return DEFAULT


def _prop_attrs(container, apply_interps, registry):
    '''First-level properties of `container` as a {str(label): [values...]} dict, values
    optionally passed through their interpretation (non-strict).'''
    value_of = None
    if apply_interps:
        from onya.interp import value_of as _value_of  # lazy: only when converting
        value_of = _value_of
    attrs: dict[str, list] = {}
    for prop in container.properties:
        val = value_of(prop, registry=registry, strict=False) if apply_interps else prop.value
        attrs.setdefault(str(prop.label), []).append(val)
    return attrs


def to_networkx(g: graph, *, apply_interps: bool = False, registry=None):
    '''
    Project `g` into a ``networkx.MultiDiGraph`` (see module docstring for the full loss
    policy). `apply_interps` (default False) passes each property value through
    ``onya.interp.value_of(..., strict=False)`` so ``@as: number`` values arrive as
    ``int``/``Decimal`` for analytics; an unknown interpretation falls back to the raw string.
    `registry` selects the interpretation registry (``None`` -> ``onya.interp.DEFAULT``); it is
    consulted only when `apply_interps` is True.
    '''
    networkx = _networkx()
    if apply_interps:
        registry = _default_registry(registry)

    mg = networkx.MultiDiGraph()

    for nid, node in g.nodes.items():
        attrs = _prop_attrs(node, apply_interps, registry)
        attrs['types'] = tuple(sorted(str(t) for t in node.types))
        mg.add_node(str(nid), **attrs)

    skipped = 0
    for node in g.nodes.values():
        for e in node.edges:
            if isinstance(e.target, assertion):  # identified-assertion target: skipped in v1
                skipped += 1
                continue
            attrs = _prop_attrs(e, apply_interps, registry)
            attrs['label'] = str(e.label)
            mg.add_edge(str(e.origin.id), str(e.target.id), key=None, **attrs)

    if skipped:
        warnings.warn(f'{skipped} edge(s) targeting identified assertions skipped in v1 nx projection',
                      stacklevel=2)
    return mg


def write_back(g: graph, label, values, *, interp=None, registry=None, replace: bool = True) -> int:
    '''
    Record analytics results back into `g` as properties, and return the number written.

    `values` maps a node id (``str`` or ``I`` — e.g. the output of
    ``networkx.betweenness_centrality``) to a Python object. Ids not present in `g` are skipped
    (not an error). This is the inverse of the projection's loss: results computed in networkx
    become first-class, typed, merge-safe Onya assertions that survive
    ``store.put(name, g, merge=True)`` and are queryable via ``graph.select``.

    - `replace=True` (default): existing properties with `label` on each touched node are
      removed before writing, so re-running analytics is idempotent rather than accumulative.
      `replace=False` accumulates.
    - `interp` given (an interpretation IRI, e.g. ``ONYA_INTERP('number')``): the value is
      written via ``onya.interp.set_value`` so it is rendered by the interpretation's
      ``from_python`` and the assertion carries the contract. `interp=None`: the value is
      written as ``str(py_obj)`` with no contract.
    - `registry` selects the interpretation registry (``None`` -> ``onya.interp.DEFAULT``);
      consulted only when `interp` is given.
    '''
    set_value = None
    if interp is not None:
        from onya.interp import set_value as _set_value  # lazy: only when writing a typed value
        set_value = _set_value
        registry = _default_registry(registry)

    written = 0
    for node_id, py_obj in values.items():
        node = g.nodes.get(node_id)
        if node is None:  # a result for a node not in this graph -> skipped, not an error
            continue
        if replace:
            for existing in list(node.getprop(label)):  # materialize before mutating the set
                node.remove_property(existing)
        if interp is not None:
            set_value(node, label, py_obj, interp, registry=registry)
        else:
            node.add_property(label, str(py_obj))
        written += 1
    return written
