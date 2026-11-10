# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.shape
'''
The shape layer: say what a graph is expected to look like, and get a report of where it doesn't.

Shapes are lightweight and RDFS-flavored, written as ordinary Onya nodes in the core namespace.
They are optional, like data contracts, and follow three rules:

- They **never infer and never mutate**. A shape reports; it does not add a type or change a value.
- They are **open** unless a class says `@closed: true`.
- Validation is **on demand**: nothing here runs while reading, and a graph that fails its shapes is
  still perfectly valid Onya.

    # Person [@Class]
    * @label: Person

    # name [@Property]
    * @appliesTo -> Person
    * @as: text
    * @cardinality: 1

    findings = validate(g, shapes=g)       # shapes may live in the graph, or in a separate one

The vocabulary and its reasoning are in `doc/design-shapes.md`. This module compiles declarations
into `Shapes` (a class and a property table, which the tables layer reads for column types) and
checks a graph against them.
'''

import re
from dataclasses import dataclass, field

from amara.iri import I

from onya.interp import DEFAULT, InterpretationRegistry, validate as validate_interps
from onya.locations import describe
from onya.ordering import OrderingError, ordered
from onya.terms import (
    ONYA, ONYA_APPLIESTO, ONYA_AS, ONYA_CARDINALITY, ONYA_CIRCUMQUERY, ONYA_CLASS, ONYA_CLOSED, ONYA_DOCUMENT,
    ONYA_LABEL, ONYA_ONEOF, ONYA_ORDERED, ONYA_PROPERTY, ONYA_RANGE, ONYA_SEVERITY, ONYA_SUBCLASSOF,
    unknown_reserved_terms,
)

SEVERITIES = ('error', 'warning')
_CARDINALITY = re.compile(r'^(?:(\d+)(?:\.\.(\d+|\*))?|\*)$')
_META = frozenset(map(str, (ONYA_CLASS, ONYA_PROPERTY, ONYA_DOCUMENT)))  # nodes that are not instance data


def parse_cardinality(text: str) -> tuple[int, int | None]:
    '''
    `(min, max)` for a UML multiplicity, `max` being None for unbounded: `1` is (1, 1), `0..1`,
    `1..*`, `0..*` and `*` (= `0..*`) mean what they say, and `n..m` is any bounded range.
    '''
    m = _CARDINALITY.match(text.strip())
    if not m:
        raise ValueError(f'{text!r} is not a cardinality: use 1, 0..1, 1..*, 0..*, or n..m')
    lo, hi = m.groups()
    if lo is None:  # the bare `*`
        return 0, None
    lo = int(lo)
    hi = lo if hi is None else None if hi == '*' else int(hi)
    if hi is not None and hi < lo:
        raise ValueError(f'{text!r} is not a cardinality: the maximum is below the minimum')
    return lo, hi


@dataclass
class Finding:
    '''One place a graph departs from its shapes (or one declaration that can't be read). Data, never an exception.'''
    severity: str  # 'error' | 'warning'
    kind: str  # applies_to | cardinality | range | one_of | as | ordering | dangling | undeclared_label | ...
    node: object  # id of the node concerned
    label: object = None  # the label concerned, if any
    detail: str = ''
    location: object = None  # a `Location`, when the read tracked locations
    assertion: object = None  # the offending assertion, if there is one

    def __str__(self) -> str:
        what = f'{self.node} {self.label}' if self.label is not None else f'{self.node}'
        return f'{self.severity} {self.kind}: {what}: {self.detail} {describe(self.location)}'


@dataclass
class Report:
    '''The result of `validate`: findings in a stable order, with the shape problems first.'''
    findings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == 'error']

    @property
    def warnings(self) -> list:
        return [f for f in self.findings if f.severity == 'warning']

    def __str__(self) -> str:
        return '\n'.join(map(str, self.findings)) if self.findings else 'Report: ok (no findings)'


@dataclass
class ClassShape:
    id: object
    label: str | None = None
    parents: set = field(default_factory=set)  # ids of the classes named by @subClassOf
    closed: bool = False
    severity: str = 'error'


@dataclass
class PropertyShape:
    id: object  # the label IRI this declaration is about
    label: str | None = None
    applies_to: set = field(default_factory=set)  # class ids; any of. Empty: any node
    range: set = field(default_factory=set)  # class ids; any of. Non-empty: the property is an edge
    interp: object = None  # the default interpretation (IRI) of its values, from `@as`
    cardinality: tuple | None = None  # (min, max or None), per node
    one_of: set = field(default_factory=set)  # allowed values
    ordered: bool = False
    severity: str = 'error'
    circum: bool = False  # its values are held in a sidecar (`@circumQuery`): see `onya.circum`


class Shapes:
    '''
    Compiled shape declarations: `classes` and `properties`, keyed by id (a property's id is its
    label IRI), and `problems`, the findings for declarations that couldn't be read. Build one with
    `load_shapes(g)`; `validate` does so itself when given a graph.
    '''
    def __init__(self):
        self.classes: dict = {}
        self.properties: dict = {}
        self.problems: list = []

    def closure(self, types) -> set:
        '''`types` and everything they are subclasses of, as strings. For validation only: nothing is inferred.'''
        seen, todo = set(), [str(t) for t in types]
        while todo:
            t = todo.pop()
            if t in seen:
                continue
            seen.add(t)
            c = self.classes.get(t)
            if c is not None:
                todo.extend(str(p) for p in c.parents)
        return seen


def _targets(n, term) -> set:
    return {str(e.target.id) for e in n.getedge(term) if hasattr(e.target, 'types')}


def load_shapes(g) -> Shapes:
    '''Read the `@Class` and `@Property` declarations in `g`. Malformed ones become `problems`, not errors.'''
    sh = Shapes()
    where = getattr(g, 'locate', lambda obj: None)

    def problem(n, kind, label, detail, assertion=None):
        sh.problems.append(Finding('error', kind, n.id, label, detail, where(assertion or n), assertion))

    def severity(n):
        found = n.values(ONYA_SEVERITY)
        if not found:
            return 'error'
        if len(found) > 1 or found[0] not in SEVERITIES:
            problem(n, 'bad_shape', ONYA_SEVERITY, f'@severity must be one of {SEVERITIES}, not {found}')
            return 'error'
        return found[0]

    def flag(n, term) -> bool:
        found = [v.lower() for v in n.values(term)]
        if any(v not in ('true', 'false') for v in found) or len(found) > 1:
            problem(n, 'bad_shape', term, f'{str(term)[len(str(ONYA)):]} must be true or false, not {found}')
        return found == ['true']

    for n in g.nodes.values():
        types = {str(t) for t in n.types}
        labels = n.values(ONYA_LABEL)
        if str(ONYA_CLASS) in types:
            sh.classes[str(n.id)] = ClassShape(
                n.id, labels[0] if labels else None, _targets(n, ONYA_SUBCLASSOF), flag(n, ONYA_CLOSED), severity(n))
        if str(ONYA_PROPERTY) in types:
            p = PropertyShape(n.id, labels[0] if labels else None, _targets(n, ONYA_APPLIESTO), _targets(n, ONYA_RANGE),
                              severity=severity(n), ordered=flag(n, ONYA_ORDERED), one_of=set(n.values(ONYA_ONEOF)),
                              circum=any(True for _ in n.getedge(ONYA_CIRCUMQUERY)))
            as_ = n.values(ONYA_AS)
            if len(as_) > 1:
                problem(n, 'bad_shape', ONYA_AS, f'a property has at most one @as, found {as_}')
            elif as_:
                p.interp = I(as_[0])
            card = n.values(ONYA_CARDINALITY)
            if len(card) > 1:
                problem(n, 'bad_shape', ONYA_CARDINALITY, f'a property has at most one @cardinality, found {card}')
            elif card:
                try:
                    p.cardinality = parse_cardinality(card[0])
                except ValueError as e:
                    problem(n, 'bad_shape', ONYA_CARDINALITY, str(e), next(iter(n.getprop(ONYA_CARDINALITY))))
            if p.range and (p.interp is not None or p.one_of):
                problem(n, 'bad_shape', ONYA_RANGE, '@range makes a property an edge, which has no @as or @oneOf')
            sh.properties[str(n.id)] = p
    return sh


def _count(found) -> int:
    '''Distinct claims: identical values (or targets) are one claim, as they would be after a merge.'''
    return len({(('e', str(a.target.id)) if hasattr(a, 'target') else ('p', a.value)) for a in found})


def validate(g, shapes=None, *, registry: InterpretationRegistry = DEFAULT, dangling: bool = False,
             allow=None, against=None) -> Report:
    '''
    Check `g` against shapes and return a `Report`. Never raises for a finding, never changes `g`.

    shapes -- where the declarations are: a graph, a `Shapes`, or None for `g` itself (or for `against`, when
        given). Nodes typed `@Class` / `@Property` / `@Document` are declarations, not data, and are not
        themselves checked.
    registry -- the interpretations that `@as` is honored with (default: the Lightweight Types)
    dangling, allow -- also report edge targets nothing declares, except those `allow` permits
        (an IRI prefix, a list of them, or a predicate; see `graph.dangling`)
    against -- a base graph, making `g` a **fragment** (a proposed change) to check as if it were merged into
        the base: a target resolves to its type in the base, and cardinality counts what the base already holds
        for a node the fragment adds to. Only findings on the nodes the fragment names are reported, so the base's
        own problems elsewhere never surface. The work is bounded by the fragment, not the base: only the nodes
        the fragment names and their neighbors are copied. A fragment that cannot merge into the base (the same
        assertion `@id` with a different content) raises `GraphMergeError`, as a `put` would. Pass a loaded
        `Shapes` when checking many fragments, so the base's declarations are read once. Locations are those of
        the merged copy, so a finding names no line.

    Checks node-level assertions against their property's declaration (`@appliesTo`, `@range`,
    `@cardinality`, `@oneOf`, `@as`, `@ordered`) and, for classes marked `@closed: true`, unknown
    labels. Every assertion's own `@as` is checked at every depth. Reserved `@` terms that nothing
    defines (a typo like `@Calss`) are reported as warnings.
    '''
    if against is not None:
        return _validate_fragment(g, against, shapes, registry, dangling, allow)
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(g if shapes is None else shapes)
    out: list = list(sh.problems)
    src = g if shapes is None else shapes
    if hasattr(src, 'nodes') and any(p.circum for p in sh.properties.values()):
        from onya.circum import declarations  # lazy: onya.circum builds on this module
        out.extend(declarations(src, sh).problems)
    is_view, sidecar_of, asked, failed = False, {}, None, set()
    if hasattr(g, 'nodes') and any(p.circum for p in sh.properties.values()):
        from onya.circum import asked, declarations as _decl, is_view as _is_view, view_findings  # from `augment`
        is_view = _is_view(g)
        sidecar_of = {pid: str(cp.sidecar.id) for pid, cp in _decl(src, sh).properties.items()}
        failed = {str(f.label) for f in view_findings(g)}  # a resolver that failed: its values aren't "missing"
    onya_ns = str(ONYA)

    def add(sev, kind, n, label, detail, assertion=None):
        out.append(Finding(sev, kind, n.id, label, detail, g.locate(assertion or n), assertion))

    by_class: dict = {}  # class id -> property shapes that name it
    for p in sh.properties.values():
        for c in p.applies_to:
            by_class.setdefault(c, []).append(p)

    for n in g.nodes.values():
        if {str(t) for t in n.types} & _META:
            continue
        closure = sh.closure(n.types)
        used: dict = {}  # label -> its assertions on this node
        for a in (*n.properties, *n.edges):
            used.setdefault(a.label, []).append(a)

        # What a shape says about each label this node uses
        for label, found in used.items():
            p = sh.properties.get(str(label))
            if p is None:
                continue
            if p.applies_to and not closure & p.applies_to:
                add(p.severity, 'applies_to', n, label,
                    f'declared for {sorted(p.applies_to)}, but this node is {sorted(closure) or "untyped"}', found[0])
            for a in found:
                _check_value(sh, registry, p, n, a, add)
            if p.ordered:
                try:
                    ordered(n, label, found)
                except OrderingError as e:
                    add(p.severity, 'ordering', n, label, e.problem, found[0])

        # What the node's classes require of labels it may not use at all, and cardinality
        applicable = {str(p.id): p for c in closure for p in by_class.get(c, ())}
        for pid, p in applicable.items():
            if p.cardinality is None:
                continue
            # A circum value isn't in the graph to count, unless this is a view that looked for it on this node
            if p.circum and not (is_view and sidecar_of.get(pid) in asked(n) and pid not in failed):
                continue
            lo, hi = p.cardinality
            found = used.get(pid, [])
            count = _count(found)
            if count < lo or (hi is not None and count > hi):
                span = f'{lo}' if hi == lo else f'{lo}..{"*" if hi is None else hi}'
                add(p.severity, 'cardinality', n, pid, f'has {count}, declared {span}', found[0] if found else None)
        closed = [sh.classes[c] for c in sorted(closure) if c in sh.classes and sh.classes[c].closed]
        if closed:
            for label, found in used.items():
                known = str(label) in applicable or (
                    str(label) in sh.properties and not sh.properties[str(label)].applies_to)
                if not known and not str(label).startswith(onya_ns):
                    add(closed[0].severity, 'undeclared_label', n, label,
                        f'{closed[0].id} is closed, and nothing declares this label for it', found[0])

    # Each assertion's own `@as`, at every depth (a shape's default is checked above, at node level)
    for f in validate_interps(g, registry=registry).findings:
        origin = f.assertion.origin
        while hasattr(origin, 'origin'):
            origin = origin.origin
        out.append(Finding('error', 'as', origin.id, f.assertion.label, f.message, f.location, f.assertion))

    for term, uses in unknown_reserved_terms(g).items():
        for use in uses:
            n = use if hasattr(use, 'types') else use.origin
            while hasattr(n, 'origin'):
                n = n.origin
            add('warning', 'unknown_reserved_term', n, term, f'{term} is not reserved by core or a loaded layer: '
                'a typo? (layers you have not loaded may define it)', None if hasattr(use, 'types') else use)

    if dangling:
        missing = g.dangling(allow)
        for n in g.nodes.values():
            for e in n.edges:
                if hasattr(e.target, 'types') and e.target.id in missing:
                    add('error', 'dangling', n, e.label, f'target {e.target.id} is referenced but never declared', e)
    return Report(out)


def _fragment_roots(fragment) -> set:
    '''The nodes whose base content matters: the ones the fragment names, and the targets of its edges (their types).'''
    return set(fragment.nodes) | {e.target.id for n in fragment.nodes.values() for e in n.edges
                                  if hasattr(e.target, 'types')}


def _validate_fragment(fragment, base, shapes, registry, dangling, allow) -> Report:
    '''`validate(fragment, against=base)`: the fragment merged into what the base holds about the nodes it touches.'''
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(base if shapes is None else shapes)
    named = {str(nid) for nid in fragment.nodes}
    work = base.subgraph(_fragment_roots(fragment))  # one hop: the touched nodes' own edges find their targets' types
    work.union(fragment.copy())
    report = validate(work, sh, registry=registry, dangling=dangling, allow=allow)
    return Report([f for f in report.findings if str(f.node) in named])


async def validate_against_store(fragment, store, names, *, shapes=None, registry: InterpretationRegistry = DEFAULT,
                                 dangling: bool = False, allow=None) -> Report:
    '''
    `validate(fragment, against=base)` for a base held in a store, which is read only where the fragment touches it.

    names -- the stored graph, or several (an authored and a runtime graph): their union is the base. A name with
        no graph yet is skipped, so a runtime graph that does not exist is not an error.
    shapes -- a graph or `Shapes`, else the declarations stored in `names` (read as just the `@Class` and `@Property`
        nodes, not the whole graph). Pass a loaded `Shapes` when checking many fragments.

    A store with `subgraph` (SQLite, PostgreSQL) hands back only the neighborhood the fragment needs. One without
    (the file store) has to read the whole of each named graph: still correct, just not bounded by the fragment.
    Everything else, including what is and is not reported, is as for `validate(..., against=)`.
    '''
    from onya.graph import graph
    from onya.store import AssertionStore, OverlayReadStore, SearchStore

    asked = [str(names)] if isinstance(names, (str, I)) else [str(n) for n in names]
    held = {str(n) async for n in store.names()}
    present = [n for n in asked if n in held]
    if not present:
        base = graph()  # nothing stored yet: the fragment stands alone
    elif not isinstance(store, AssertionStore):
        base = await store.get(present[0])
        for n in present[1:]:
            base.union(await store.get(n))
    else:
        roots = _fragment_roots(fragment)
        if shapes is None:  # the declarations only: they are few, and the base is not
            if not isinstance(store, SearchStore):
                raise ValueError('this store cannot list its @Class and @Property nodes: pass shapes=')
            decl = {str(i) for n in present for t in (ONYA_CLASS, ONYA_PROPERTY)
                    async for i in store.nodes_by_type(n, t)}
            shapes = load_shapes(await _stored_neighborhood(store, present, decl, 0, OverlayReadStore))
        base = await _stored_neighborhood(store, present, roots, 1, OverlayReadStore)
    return _validate_fragment(fragment, base, shapes, registry, dangling, allow)


async def _stored_neighborhood(store, names, roots, hops, overlay_cls):
    '''`roots` and their neighbors out of the stored graph `names`, as one in-memory graph.'''
    if len(names) > 1 and isinstance(store, overlay_cls):
        return await store.subgraph_across(names, set(roots), hops)
    g = await store.subgraph(names[0], set(roots), hops)
    for n in names[1:]:  # several graphs on a store that cannot read across them
        g.union(await store.subgraph(n, set(roots), hops))
    return g


def _check_value(sh, registry, p, n, a, add) -> None:
    '''Value-level checks of one node-level assertion against its property's declaration.'''
    is_edge = hasattr(a, 'target')
    if is_edge:
        if p.interp is not None or p.one_of:
            add(p.severity, 'range', n, a.label, f'declared as a value, but this is an edge to {a.target.id}', a)
        elif p.range and hasattr(a.target, 'types') and not sh.closure(a.target.types) & p.range:
            got = sorted(sh.closure(a.target.types)) or 'untyped'
            add(p.severity, 'range', n, a.label, f'target {a.target.id} is {got}, declared {sorted(p.range)}', a)
        return
    if p.range:
        add(p.severity, 'range', n, a.label, f'declared as an edge to {sorted(p.range)}, but this is a value', a)
    if p.one_of and a.value not in p.one_of:
        add(p.severity, 'one_of', n, a.label, f'{a.value!r} is not one of {sorted(p.one_of)}', a)
    # The declaration is a default: an assertion's own @as wins, and is checked with the others below
    if p.interp is not None and a.interp is None:
        interp = registry.get(p.interp)
        if interp is not None and not interp.check(a.value):
            add(p.severity, 'as', n, a.label, f'{a.value!r} is not a valid {p.interp}', a)
