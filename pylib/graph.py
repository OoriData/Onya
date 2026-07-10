# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.graph
'''
Graph and other fundamental classes for Onya

The Onya graph model:
- A graph is a collection of nodes
- Each node has:
  - An identifier (IRI)
  - A set of types (IRIs)
  - A set of assertions (edges and properties)
- Edges connect nodes to nodes via IRI labels
- Properties connect nodes to string values via IRI labels
- Both edges and properties are collectively called "assertions"
- Each assertion is anonymous by default, distinguished by (origin, label, target/value);
  it MAY carry an explicit identifier (`id`), making it addressable like a node
- Assertions can themselves be origins for further assertions (natural recursiveness)
'''

from __future__ import annotations
from collections.abc import MutableMapping, Iterator
from abc import ABC

from amara.iri import I

from onya.terms import ONYA_ASSERTION


class AssertionIdConflict(ValueError):
    '''
    Raised when an assertion identifier is not unique within the graph — either it is
    already bound to a different assertion, or it collides with a node id. Assertion
    ids share the same identifier space as node ids (see SPEC: Assertion Identifiers).
    '''


class GraphMergeError(ValueError):
    '''
    Raised when a graph merge violates an identity rule (see SPEC: Identity and graph
    merge). Two assertions bearing the same explicit `id` must agree on their skeleton;
    a mismatch — a differing (label, value/target), or a differing non-absent `interp` —
    is a merge error, consistent with the skeleton-mismatch rule for identified
    assertions.
    '''


class assertions_mixin:
    '''
    Mixin for objects that can have assertions (edges and properties)
    '''
    def add_property(self, label: I | str, value: str, interp: I | str | None = None):
        p = property_(self, label, value)
        if interp is not None:
            p.interp = interp
        self.properties.add(p)
        return p

    def add_edge(self, label: I | str, target: 'node'):
        e = edge(self, label, target)
        self.edges.add(e)
        return e

    def remove_property(self, prop: 'property_'):
        self.properties.remove(prop)

    def remove_edge(self, edge_: 'edge'):
        self.edges.remove(edge_)

    def getprop(self, label: I | str):
        '''Get properties with a given label'''
        for prop in self.properties:
            if prop.label == label:
                yield prop
    
    def getedge(self, label: I | str):
        '''Get edges with a given label'''
        for edge_ in self.edges:
            if edge_.label == label:
                yield edge_


class node(assertions_mixin):
    '''
    A node in the Onya graph.
    
    A node has an identifier (IRI), optional types (IRIs), and assertions
    (edges and properties). Both edges and properties are sets, not sequences,
    because pervasive ordering is not a core requirement of the model.
    '''
    __slots__ = ['id', 'types', 'properties', 'edges']

    def __init__(self, id_: I | str, types: I | str | set[I | str] | None = None):
        self.id = id_
        if isinstance(types, str):
            types = I(types)
        if isinstance(types, I):
            types = {types}
        self.types: set[I | str] = set(types) if types else set()
        self.properties: set['property_'] = set()
        self.edges: set['edge'] = set()
    
    def traverse(self, label: I | str) -> Iterator['edge']:
        '''Find edges with a given label'''
        for e in self.edges:
            if e.label == label:
                yield e

    def reverse(self, label: I | str, graph: 'graph') -> Iterator['edge']:
        '''Find edges targeting this node with a given label (requires graph access)'''
        for nid, nobj in graph.nodes.items():
            for e in nobj.traverse(label):
                if e.target == self:
                    yield e


class assertion(assertions_mixin, ABC):
    '''
    Abstract base class for assertions (edges and properties)

    Each assertion is anonymous by default, distinguished by the combination of
    its origin and its label IRI (plus target/value). It MAY carry an explicit
    identifier (`id`, an IRI in the same space as node ids), making it addressable
    as the target of an edge. `id` is None unless one has been assigned.

    Every assertion carries the implicit type `onya:Assertion` (exposed, read-only, as
    `types` for uniformity with `node.types`). This lets a consumer that has resolved an
    edge target distinguish an identified assertion from an ordinary node by a type check.
    The implicit type is class-level and shared: it is not stored per instance and is not
    serialized.
    '''
    __slots__ = ['origin', 'label', 'id', 'interp', 'properties', 'edges']

    # Implicit, read-only type shared by all assertions (see class docstring). frozenset so
    # it cannot be mutated through an instance; not part of __slots__, so purely class-level.
    types = frozenset({ONYA_ASSERTION})

    def __init__(self, origin: 'node | assertion', label: I | str):
        self.origin = origin
        self.label = label
        self.id: I | str | None = None  # optional explicit identifier; see SPEC: Assertion Identifiers
        # Optional interpretation: a recorded contract about how this assertion's string value is
        # meant to be read (see SPEC: Data contract layers). Excluded from the merge skeleton, like
        # `id`; the model stores the IRI as data and never applies it. None means no contract.
        self.interp: I | str | None = None
        self.properties: set['property_'] = set()
        self.edges: set['edge'] = set()


class property_(assertion):
    '''
    A property assertion connects an origin to a string value via an IRI label.
    
    Properties in Onya are simple: they always have string values.
    No numbers, dates, or other types at the core layer - those can be
    handled by annotation systems built on top.
    '''
    __slots__ = ['value']

    def __init__(self, origin: 'node | assertion', label: I | str, value: str):
        super().__init__(origin, label)
        self.value: str = value

    def __repr__(self):
        return f'property_({self.label}={self.value!r})'

    @property
    def _skeleton(self):
        '''
        Identity core used for merge (see SPEC: Identity and graph merge). Excludes the
        `id`, the `interp`, and nested assertions: annotating an assertion never changes
        its identity. Origin is excluded because skeletons are only ever compared among
        assertions that already share an origin (siblings under one container).
        '''
        return ('property', self.label, self.value)


class edge(assertion):
    '''
    An edge assertion connects an origin node to a target node via an IRI label.
    '''
    __slots__ = ['target']

    def __init__(self, origin: 'node | assertion', label: I | str, target: 'node'):
        super().__init__(origin, label)
        self.target: 'node' = target
    
    def __repr__(self):
        target_id = self.target.id if self.target is not None else '?'
        return f'edge({self.label} -> {target_id})'

    @property
    def _skeleton(self):
        '''
        Identity core used for merge (see `property_._skeleton`). An edge's target is part
        of its skeleton. An identified assertion target is keyed by object identity (it is
        a distinct occurrence); an ordinary node target is keyed by its node id, so the
        same edge extracted from two sources — pointing at the same node — merges.
        '''
        tgt = self.target
        if isinstance(tgt, assertion):
            target_key = ('assertion', id(tgt))
        else:
            target_key = ('node', tgt.id if tgt is not None else None)
        return ('edge', self.label, target_key)


def _absorb(keeper: assertion, other: assertion) -> None:
    '''
    Fold `other` into `keeper` (already found to be the same assertion): the keeper adopts
    an interp it lacks (one-sided adoption), then `other`'s nested assertions are reparented
    onto the keeper. The caller re-merges the combined nested set.
    '''
    if keeper.interp is None and other.interp is not None:
        keeper.interp = other.interp
    for p in other.properties:
        p.origin = keeper
        keeper.properties.add(p)
    for e in other.edges:
        e.origin = keeper
        keeper.edges.add(e)


def _merge_identified(rows: list) -> list:
    '''
    Collapse identified assertions (Rule 1): rows sharing an explicit id are the same
    assertion, so their skeletons MUST match and their interps must be compatible
    (equal-or-one-absent) — a mismatch is a `GraphMergeError`. Nested assertions are
    unioned. Rows with distinct ids stay distinct. (Rule 3 — identified never merges with
    anonymous — falls out because anonymous rows are grouped separately.)
    '''
    keepers: dict = {}
    order: list = []
    for a in rows:
        keeper = keepers.get(a.id)
        if keeper is None:
            keepers[a.id] = a
            order.append(a.id)
            continue
        if keeper._skeleton != a._skeleton:
            raise GraphMergeError(
                f'Assertions sharing id {a.id!r} have mismatched skeletons: '
                f'{keeper._skeleton!r} vs {a._skeleton!r}'
            )
        ki, ai = keeper.interp, a.interp
        if ki is not None and ai is not None and ki != ai:
            raise GraphMergeError(
                f'Assertions sharing id {a.id!r} carry differing interpretations: '
                f'{ki!r} vs {ai!r}'
            )
        _absorb(keeper, a)
    return [keepers[i] for i in order]


def _merge_anonymous_skeleton_group(rows: list) -> list:
    '''
    Collapse anonymous assertions that share a skeleton (Rule 2), partitioned by interp:

    - Rows with the same non-absent interp merge into one (nested unioned).
    - Rows carrying *different* non-absent interps stay distinct — two parties attaching
      different contracts to the same words make genuinely different claims (not an error).
    - Interp-free (NULL) rows: if the group has no contract, they merge into a single NULL
      row; if it has exactly one contract, they merge into it (one-sided adoption). But if
      the group already holds two or more *differing* contracts, a NULL row merges into
      **neither** and is dropped — its skeleton is already represented and a contract-free
      claim, unable to pick a side, adds nothing. (Ratified ruling; see the interpretation
      design docs. A dropped NULL's own nested assertions go with it, since there is no
      non-arbitrary contract row to attach them to.)
    '''
    by_interp: dict = {}
    interp_order: list = []
    nulls: list = []
    for r in rows:
        if r.interp is None:
            nulls.append(r)
            continue
        keeper = by_interp.get(r.interp)
        if keeper is None:
            by_interp[r.interp] = r
            interp_order.append(r.interp)
        else:
            _absorb(keeper, r)
    survivors = [by_interp[i] for i in interp_order]

    if not survivors:  # no contract in the group: all NULLs are one claim
        keeper = nulls[0]
        for other in nulls[1:]:
            _absorb(keeper, other)
        return [keeper]
    if len(survivors) == 1:  # a single contract: NULLs adopt it (one-sided)
        keeper = survivors[0]
        for other in nulls:
            _absorb(keeper, other)
        return survivors
    # Two or more differing contracts already present: a NULL can pick no side, so it is
    # dropped as redundant (skeleton already represented).
    return survivors


def _merge_container(container) -> None:
    '''
    Collapse the direct child assertions of `container` (a node or an assertion) into one
    occurrence each per the SPEC identity rules, then recurse into the survivors.
    Order-independent and idempotent: re-running on an already-merged container is a no-op.
    '''
    for attr in ('properties', 'edges'):
        identified: list = []
        anon_by_skeleton: dict = {}
        for a in getattr(container, attr):
            if a.id is not None:
                identified.append(a)
            else:
                anon_by_skeleton.setdefault(a._skeleton, []).append(a)

        kept = _merge_identified(identified)
        for group in anon_by_skeleton.values():
            kept.extend(_merge_anonymous_skeleton_group(group))

        setattr(container, attr, set(kept))
        for a in kept:
            _merge_container(a)


class graph(MutableMapping):
    '''
    A collection of nodes managed and queried together.

    This is the top-level container for an Onya graph.
    '''
    def __init__(self, nodes: list[node] = ()):
        self.nodes: dict[I | str, node] = {}
        self.nodes.update({n.id: n for n in nodes})
        # Explicit assertion identifiers (see SPEC: Assertion Identifiers), sharing the
        # node id space. Maps id -> assertion, so an identified assertion can be an edge target.
        self.assertion_ids: dict[I | str, assertion] = {}

    def __getitem__(self, key: I | str) -> node:
        return self.nodes[key]

    def __delitem__(self, nid: I | str) -> None:
        del self.nodes[nid]

    def __setitem__(self, nid: I | str, nobj: node) -> None:
        self.nodes[nid] = nobj

    def __iter__(self) -> Iterator[I | str]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        return f'{type(self).__name__} with {len(self.nodes)} nodes'

    def node(self, nid: I | str, types: I | str | set[I | str] | None = None) -> node:
        '''
        Convenience for constructing, then adding a new node to the graph
        '''
        n = node(nid, types)
        self[nid] = n
        return n

    def register_assertion_id(self, id_: I | str, assertion_obj: assertion) -> assertion:
        '''
        Bind an explicit identifier to an assertion, enforcing uniqueness among
        assertion ids. Sets `assertion_obj.id` and records it so the assertion can be
        used as an edge target. Raises `AssertionIdConflict` if `id_` is already bound
        to a different assertion. (Collision against node ids shares the same id space
        and is validated separately once all nodes and ids are known.)
        '''
        existing = self.assertion_ids.get(id_)
        if existing is not None and existing is not assertion_obj:
            raise AssertionIdConflict(f'Assertion id {id_!r} is already assigned to another assertion')
        assertion_obj.id = id_
        self.assertion_ids[id_] = assertion_obj
        return assertion_obj

    def merge(self) -> 'graph':
        '''
        Normalize the graph by collapsing duplicate assertions into a single occurrence,
        per the SPEC identity rules (idempotent graph union). Anonymous assertions with
        equal skeletons merge, unioning their nested assertions recursively; assertions
        sharing an explicit `id` merge and must agree (else `GraphMergeError`); an
        identified assertion never merges with an anonymous one.

        This is an **explicit, on-demand** operation — never called automatically.
        Parsing several overlapping documents into one graph accumulates their assertions
        as distinct occurrences; they collapse only when a consumer calls `merge()`.
        '''
        for n in self.nodes.values():
            _merge_container(n)
        return self

    def _iter_assertions(self) -> Iterator[assertion]:
        '''Yield every assertion in the graph, recursively (properties then edges).'''
        def rec(container):
            for a in list(container.properties):
                yield a
                yield from rec(a)
            for a in list(container.edges):
                yield a
                yield from rec(a)
        for n in self.nodes.values():
            yield from rec(n)

    def _rebind_node_targets(self) -> None:
        '''
        Point every node-valued edge target at this graph's canonical node object for that
        id. After a `union`, edges brought in from the other graph still reference the other
        graph's node objects; rebinding keeps traversal and `reverse()` consistent. Edge
        targets that are identified assertions are handled in `_reindex_assertion_ids`.
        '''
        for a in self._iter_assertions():
            if isinstance(a, edge):
                tgt = a.target
                if tgt is not None and not isinstance(tgt, assertion):
                    canon = self.nodes.get(tgt.id)
                    if canon is not None:
                        a.target = canon

    def _reindex_assertion_ids(self) -> None:
        '''
        Rebuild `assertion_ids` from the assertions that actually survive in the graph, then
        rebind any edge pointing at an identified assertion to the surviving occurrence. A
        `merge()` collapses same-id duplicates onto one keeper; this makes the id index and
        edge targets agree with that keeper.
        '''
        surviving: dict[I | str, assertion] = {}
        for a in self._iter_assertions():
            if a.id is not None:
                surviving[a.id] = a
        self.assertion_ids = surviving
        for a in self._iter_assertions():
            if isinstance(a, edge) and isinstance(a.target, assertion) and a.target.id is not None:
                canon = surviving.get(a.target.id)
                if canon is not None:
                    a.target = canon

    def validate_id_space(self) -> None:
        '''
        Enforce the shared identifier space (SPEC: Assertion Identifiers): no explicit
        assertion `@id` may equal a node id. Raises `AssertionIdConflict` listing the
        offending ids. The parser checks this at parse time; the store write path calls it
        so a graph assembled programmatically (or by `union`) cannot persist a collision.
        '''
        collisions = set(self.assertion_ids) & set(self.nodes)
        if collisions:
            raise AssertionIdConflict(
                f'Assertion id(s) collide with node id(s): {sorted(map(str, collisions))}'
            )

    def union(self, other: 'graph') -> 'graph':
        '''
        Merge `other` into this graph, in place, and normalize per the SPEC identity rules —
        the model-level graph union that every store backend's ``put(merge=True)`` is defined
        against. Nodes present in both graphs combine (types unioned, assertions accumulated);
        nodes only in `other` are adopted. Explicit assertion ids carry over. Node-valued
        edge targets are then rebound to this graph's canonical node objects and the combined
        assertions are collapsed by `merge()`, so the result is observationally identical to
        parsing both sources into one graph and calling `merge()`.

        Raises `GraphMergeError` on a Rule 1 violation (same `@id`, mismatched skeleton or
        conflicting non-absent interp) and `AssertionIdConflict` on a node-id vs
        assertion-id collision.
        '''
        for nid, onode in other.nodes.items():
            keeper = self.nodes.get(nid)
            if keeper is None:
                self.nodes[nid] = onode
                continue
            keeper.types |= set(onode.types)
            for p in list(onode.properties):
                p.origin = keeper
                keeper.properties.add(p)
            for e in list(onode.edges):
                e.origin = keeper
                keeper.edges.add(e)
        for aid, a in other.assertion_ids.items():
            self.assertion_ids.setdefault(aid, a)
        self._rebind_node_targets()
        self.validate_id_space()
        self.merge()
        self._reindex_assertion_ids()
        return self

    def typematch(self, types: I | str | set[I | str]) -> Iterator[node]:
        '''Find nodes with matching types'''
        if isinstance(types, (str, I)):
            types = {types}
        types_set = set(types)
        for n in self.nodes.values():
            if n.types & types_set:
                yield n

    def match(self, origin: I | str) -> Iterator[tuple[I | str, I | str, str | I, dict]]:
        '''
        Match all assertions (properties and edges) for a given origin node.
        
        Returns an iterator of tuples: (origin, relation, target, annotations)
        - origin: the node ID (same as input)
        - relation: the property/edge label (IRI)
        - target: for properties, the string value; for edges, the target ID
        - annotations: dict mapping property labels to values from assertion properties

        An edge target ID may name either a node or an *identified assertion* (an edge whose
        RHS was another assertion's `@id`; see SPEC: Assertion Identifiers). To tell them
        apart, resolve the target: `self.assertion_ids.get(target)` yields the assertion (or
        None), and every assertion carries the implicit `onya:Assertion` type — so
        `ONYA_ASSERTION in obj.types` (or `isinstance(obj, assertion)`) is the type check that
        interprets the result. A future projection/traversal layer will formalize this.
        '''
        if origin not in self.nodes:
            return
        
        node_obj = self.nodes[origin]
        
        # Helper to convert assertion properties to a dict
        def props_to_dict(assertion_obj):
            '''Convert a set of properties to a dict (last value wins for duplicates)'''
            result = {}
            for prop in assertion_obj.properties:
                result[prop.label] = prop.value
            return result
        
        # Yield all properties
        for prop in node_obj.properties:
            annotations = props_to_dict(prop)
            yield (origin, prop.label, prop.value, annotations)
        
        # Yield all edges
        for edge_obj in node_obj.edges:
            annotations = props_to_dict(edge_obj)
            yield (origin, edge_obj.label, edge_obj.target.id, annotations)
