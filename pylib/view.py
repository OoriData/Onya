# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.view
'''
Declarative read-side projection: "show me this thing".

A *view spec* says which properties of a node to show, in what order, which edges (outbound
or inbound) to follow, and what to show of each linked node and of the link itself. `project`
turns a node plus the specs into an ordered, plain-data structure; rendering it (HTML,
Markdown, a chat message, JSON for an API or an LLM tool) stays with the application.

This is projection, not validation: a view never rejects a graph. Absent fields are omitted,
an empty follow is `[]`, malformed interpreted values fall back to their raw string.

Spec format (plain data — a dict/list, so TOML, YAML, and JSON all load the same way):

    [[view]]
    type = "schema:Person"                 # str or list; or `when = "<name>"` for a caller hook
    label = ["{givenName} {familyName}", "name"]   # optional; default: first field's value
    fields = ["name", { label = "email", many = true }]

      [[view.follow]]
      edge = "worksFor"                    # or `inbound = "author"` (nodes whose edge points here)
      as = "employer"                      # output key; default: the label (`^label` for inbound)
      show = ["name", "url"]               # omit to show the target with its own matching view
      edge_props = ["startDate", { edge = "ex:role", show = ["name"] }]
      limit = 10
      order_by = "-datePublished"          # a field of the linked node; leading `-` = descending

Labels (`fields`, `edge`, `type`, ...) are full IRIs, CURIEs, or bare `@schema` names, resolved
against the graph's `prefixes` at projection time — a spec is graph-independent data.

Output, per node (keys in this order, each present only when it applies):

    {'id': I, 'type': str, 'label': str | None, 'fields': [(name, value), ...],
     'edge': [(name, value | [item, ...]), ...],     # follow items with edge_props only
     '<follow as>': [item, ...], ...,
     'truncated': 'depth' | 'cycle'}

`value` is one value, or a list for `many = true`. Values of properties with an `@as` come
back typed via `onya.interp.value_of` (`raw = true` per field, or `project(raw=True)`, keeps
strings); an edge named as a field yields its target id. Ids and edge targets are `amara.iri.I`
— full IRIs, equal to their plain strings and JSON-encodable as-is, but `isinstance(v, I)` tells a
link from a text value that happens to look like one (as does an `@as: iri` value). `type` is a
compacted display string. Everything is JSON-serializable except typed `@as` values like
`Decimal`/`datetime` — `jsonable()` converts those losslessly where it can.
'''

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, time
from decimal import Decimal

from amara.iri import I

from onya.graph import assertion, graph, node
from onya.interp import DEFAULT, InterpretationError, InterpretationRegistry, value_of
from onya.util import compact_iri

__all__ = ['View', 'Field', 'Follow', 'load', 'project', 'project_from_store', 'jsonable', 'to_text',
           'DEFAULT_MAX_DEPTH']

DEFAULT_MAX_DEPTH = 3
RESERVED_KEYS = frozenset({'id', 'type', 'label', 'fields', 'edge', 'truncated'})


# --- spec model -----------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    '''One value slot: a property (or edge, yielding target ids) shown under `name`.'''
    label: str
    name: str
    many: bool = False
    raw: bool = False


@dataclass(frozen=True)
class Follow:
    '''
    Follow `label` edges outbound (or `inbound`), projecting each linked node with `show`
    (and `label`/`follow` alongside it) — or, when `show` is None, with the linked node's own
    matching view. `edge_props` projects the link assertion itself: fields, or nested follows
    of edges asserted on the link.
    '''
    label: str
    name: str
    inbound: bool = False
    show: tuple[Field, ...] | None = None
    label_spec: tuple[str, ...] | None = None
    follow: tuple['Follow', ...] = ()
    edge_props: tuple['Field | Follow', ...] = ()
    limit: int | None = None
    order_by: str | None = None
    desc: bool = False


@dataclass(frozen=True)
class View:
    '''A per-node-kind spec, selected by `types` (any match) and/or the caller's `when` hook.'''
    types: tuple[str, ...] = ()
    when: Callable | str | None = None
    fields: tuple[Field, ...] = ()
    label_spec: tuple[str, ...] | None = None
    follow: tuple[Follow, ...] = ()


def _check_keys(d: Mapping, allowed: set, what: str) -> None:
    unknown = set(d) - allowed
    if unknown:
        raise ValueError(f'Unknown {what} key(s) {sorted(unknown)}; allowed: {sorted(allowed)}')


def _as_tuple(v) -> tuple:
    if v is None:
        return ()
    return (v,) if isinstance(v, str) else tuple(v)


def _load_field(d) -> Field:
    if isinstance(d, Field):
        return d
    if isinstance(d, str):
        return Field(label=d, name=d)
    _check_keys(d, {'label', 'as', 'many', 'raw'}, 'field')
    if 'label' not in d:
        raise ValueError(f'A field needs a `label`: {d!r}')
    return Field(label=d['label'], name=d.get('as', d['label']), many=bool(d.get('many', False)),
                 raw=bool(d.get('raw', False)))


def _default_name(f: 'Follow') -> str:
    return f'^{f.label}' if f.inbound else f.label


def _describe_follow(f: 'Follow') -> str:
    return f'`{"inbound" if f.inbound else "edge"} = "{f.label}"`'


def _free_name(base: str, taken: set, *, numbered: bool = False) -> str:
    '''A suggested output name: `base` itself if free, else `base_links` (or `base_2`, ...).'''
    numbers = [f'{base}_{i}' for i in range(2, 100)]
    candidates = [base] + (numbers if numbered else [f'{base}_links'] + numbers)
    return next(c for c in candidates if c not in RESERVED_KEYS and c not in taken)


def _check_names(follows: Iterable['Follow'], where: str) -> None:
    '''
    Follow results become keys of the output item, so their names must not shadow the item's
    own keys, nor each other. Errors say where the name came from and suggest a free one.
    '''
    follows = list(follows)
    taken = {f.name for f in follows}
    seen: dict = {}
    for f in follows:
        explicit = f.name != _default_name(f)
        origin = (f'has `as = "{f.name}"`' if explicit else
                  f'would be output under "{f.name}" (a follow\'s output key defaults to its '
                  f'{"inbound " if f.inbound else ""}label)')
        if f.name in RESERVED_KEYS:
            fix = 'Pick another name' if explicit else 'Add an `as` to name it'
            suggestion = _free_name(_default_name(f) if explicit else f.name, taken)
            raise ValueError(
                f'{where}: follow {_describe_follow(f)} {origin}, but "{f.name}" is reserved — '
                f'output items use it for their own {f.name!r} entry (reserved: '
                f'{", ".join(sorted(RESERVED_KEYS))}). {fix}, e.g. `as = "{suggestion}"`.'
            )
        if f.name in seen:
            other = seen[f.name]
            suggestion = _free_name(f.name, taken, numbered=True)
            raise ValueError(
                f'{where}: follows {_describe_follow(other)} and {_describe_follow(f)} would both be '
                f'output under "{f.name}", so one would overwrite the other. Give one a distinct '
                f'`as`, e.g. `as = "{suggestion}"` on the second.'
            )
        seen[f.name] = f


def _describe_view(d: Mapping) -> str:
    if d.get('type'):
        t = d['type']
        return f'View `type = {t!r}`' if isinstance(t, str) else f'View `type = {list(t)!r}`'
    if d.get('when') is not None:
        return f'View `when = {d["when"]!r}`'
    return 'View (no type/when)'


def _load_follow(d) -> Follow:
    if isinstance(d, Follow):
        return d
    _check_keys(d, {'edge', 'inbound', 'as', 'show', 'label', 'follow', 'edge_props', 'limit', 'order_by'},
                'follow')
    if ('edge' in d) == ('inbound' in d):
        raise ValueError(f'A follow takes exactly one of `edge` or `inbound`: {d!r}')
    inbound = 'inbound' in d
    label = d['inbound'] if inbound else d['edge']
    if 'follow' in d and 'show' not in d:
        raise ValueError(f'A nested `follow` needs `show` alongside it (without `show`, the linked '
                         f"node's own view decides what follows): {d!r}")
    order_by = d.get('order_by')
    desc = bool(order_by and order_by.startswith('-'))
    nested = tuple(_load_follow(f) for f in d.get('follow', ()))
    _check_names(nested, f'Inside follow `{"inbound" if inbound else "edge"} = "{label}"`')
    edge_props = tuple(_load_follow(e) if isinstance(e, Mapping) and ('edge' in e or 'inbound' in e)
                       else _load_field(e) for e in d.get('edge_props', ()))
    if any(isinstance(e, Follow) and e.inbound for e in edge_props):
        raise ValueError(f'`edge_props` can follow edges asserted on the link, not inbound ones: {d!r}')
    limit = d.get('limit')
    return Follow(
        label=label, name=d.get('as', f'^{label}' if inbound else label), inbound=inbound,
        show=None if 'show' not in d else tuple(_load_field(f) for f in d['show']),
        label_spec=None if 'label' not in d else _as_tuple(d['label']),
        follow=nested, edge_props=edge_props,
        limit=None if limit is None else int(limit),
        order_by=order_by[1:] if desc else order_by, desc=desc,
    )


def _load_view(d) -> View:
    if isinstance(d, View):
        return d
    _check_keys(d, {'type', 'when', 'fields', 'label', 'follow'}, 'view')
    follow = tuple(_load_follow(f) for f in d.get('follow', ()))
    _check_names(follow, _describe_view(d))
    return View(types=_as_tuple(d.get('type')), when=d.get('when'),
                fields=tuple(_load_field(f) for f in d.get('fields', ())),
                label_spec=None if 'label' not in d else _as_tuple(d['label']), follow=follow)


def load(data) -> tuple[View, ...]:
    '''
    Build view specs from plain data: a mapping with a `view` list (the TOML
    `[[view]]` shape), a list of view dicts, or a single view dict. Already-built `View`s
    pass through. Unknown keys raise `ValueError`, so a typo never silently shows nothing.
    '''
    if isinstance(data, View):
        return (data,)
    if isinstance(data, Mapping):
        data = data['view'] if 'view' in data else [data]
    return tuple(_load_view(v) for v in data)


# --- values ---------------------------------------------------------------------------

def _iri(x) -> I:
    '''Ids and edge targets come back as `I`: a `str` subclass, so equal to (and JSON-encoded as)
    the plain string, yet distinguishable from a text value that merely looks like an IRI.'''
    return x if isinstance(x, I) else I(str(x))


def _sort_key(v) -> tuple:
    '''Total, deterministic order over mixed values: numbers numerically, else by text form.'''
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return (0, v, '')
    if isinstance(v, (datetime, date, time)):
        return (1, 0, v.isoformat())
    return (1, 0, str(v))


def jsonable(obj):
    '''
    Convert a `project` result to JSON-native types: `Decimal` -> `int` when integral, else
    `float` when that round-trips exactly, else `str`; dates/times -> ISO 8601 strings;
    tuples -> lists; IRIs -> `str`.
    '''
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        if obj == obj.to_integral_value():
            return int(obj)
        f = float(obj)
        return f if Decimal(repr(f)) == obj else str(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, str):
        return str(obj)  # I -> plain str
    return obj


# --- projection -----------------------------------------------------------------------

_PLACEHOLDER = re.compile(r'\{([^{}]+)\}')


class _Projector:
    '''One projection pass over a graph. `tracker` (store mode) records what was missing.'''

    def __init__(self, g: graph, views: tuple[View, ...], *, predicates, max_depth: int, raw: bool,
                 registry: InterpretationRegistry, tracker=None):
        self.g = g
        self.views = views
        self.predicates = predicates or {}
        self.max_depth = max_depth
        self.raw = raw
        self.registry = registry
        self.tracker = tracker
        self._resolved: dict = {}

    def res(self, label: str):
        r = self._resolved.get(label)
        if r is None:
            r = self._resolved[label] = self.g.resolve(label)
        return r

    def need(self, obj) -> None:
        if self.tracker is not None and isinstance(obj, node):
            self.tracker.need(obj.id)

    # values

    def values(self, container, label: str, raw: bool) -> list:
        lbl = self.res(label)
        out = []
        for p in container.properties:
            if p.label != lbl:
                continue
            if raw or self.raw or p.interp is None:
                out.append(p.value)
                continue
            try:
                out.append(value_of(p, registry=self.registry, strict=False))
            except InterpretationError:  # a view shows what's there; never rejects
                out.append(p.value)
        out.extend(_iri(e.target.id) for e in container.edges if e.label == lbl and e.target is not None)
        out.sort(key=_sort_key)
        return out

    def first(self, container, label: str):
        vals = self.values(container, label, False)
        return vals[0] if vals else None

    def field_pairs(self, container, fields: Iterable[Field]) -> list:
        pairs = []
        for f in fields:
            vals = self.values(container, f.label, f.raw)
            if vals:
                pairs.append((f.name, vals if f.many else vals[0]))
        return pairs

    def label(self, container, label_spec, fields) -> str | None:
        candidates = label_spec if label_spec is not None else ((fields[0].label,) if fields else ())
        for cand in candidates:
            if '{' in cand:
                parts, ok = {}, True
                for ph in _PLACEHOLDER.findall(cand):
                    v = self.first(container, ph.strip())
                    if v is None:
                        ok = False
                        break
                    parts[ph] = str(v)
                if ok:
                    return _PLACEHOLDER.sub(lambda m: parts[m.group(1)], cand)
            else:
                v = self.first(container, cand)
                if v is not None:
                    return str(v)
        return None

    # spec selection

    def select_view(self, obj) -> View | None:
        types = getattr(obj, 'types', frozenset())
        for v in self.views:
            if v.types and not any(self.res(t) in types for t in v.types):
                continue
            if v.when is not None:
                pred = v.when if callable(v.when) else self.predicates.get(v.when)
                if pred is None:
                    raise KeyError(f'View `when` hook {v.when!r} has no entry in `predicates`')
                if not pred(obj, self.g):
                    continue
            return v
        return None

    # items

    def item(self, obj, *, fields, label_spec, follows, depth: int, path: frozenset,
             type_of: View | None = None, link=None, edge_props=()) -> dict:
        self.need(obj)
        oid = _iri(obj.id) if obj.id is not None else None
        out: dict = {'id': oid}
        if type_of is not None and type_of.types:
            matched = next((t for t in type_of.types if self.res(t) in obj.types), None)
            if matched is not None:  # (a forced `spec=` may not match the node's types)
                out['type'] = compact_iri(str(self.res(matched)), self.g.prefixes, fallback='full')
        out['label'] = self.label(obj, label_spec, fields)
        if obj.id is not None and obj.id in path:
            out['truncated'] = 'cycle'
            return out
        out['fields'] = self.field_pairs(obj, fields)
        truncated = False
        inner_path = path | {obj.id} if obj.id is not None else path
        if link is not None and edge_props:
            pairs = []
            for ep in edge_props:
                if isinstance(ep, Field):
                    vals = self.values(link, ep.label, ep.raw)
                    if vals:
                        pairs.append((ep.name, vals if ep.many else vals[0]))
                elif depth < self.max_depth:
                    pairs.append((ep.name, self.follow(link, ep, depth, inner_path)))
                else:
                    truncated = True
            out['edge'] = pairs
        if follows:
            if depth < self.max_depth:
                for f in follows:
                    out[f.name] = self.follow(obj, f, depth, inner_path)
            else:
                truncated = True
        if truncated:
            out['truncated'] = 'depth'
        return out

    def links(self, origin, f: Follow) -> list:
        '''(link assertion, linked object) pairs for follow `f` from `origin`.'''
        lbl = self.res(f.label)
        if f.inbound:
            if not isinstance(origin, node):
                return []
            if self.tracker is not None:
                self.tracker.need_inbound(origin.id, lbl)
            # First-level edges only (the linked thing is a node that links here), matching
            # what a store can answer; nested edges pointing here aren't "nodes linking here".
            return [(e, e.origin) for e in self.g.inbound(origin, label=lbl) if isinstance(e.origin, node)]
        return [(e, e.target) for e in origin.edges if e.label == lbl and e.target is not None]

    def follow(self, origin, f: Follow, depth: int, path: frozenset) -> list:
        items = []
        for link, other in self.links(origin, f):
            if f.show is not None:
                it = self.item(other, fields=f.show, label_spec=f.label_spec, follows=f.follow,
                               depth=depth + 1, path=path, link=link, edge_props=f.edge_props)
            else:
                v = self.select_view(other) if not isinstance(other, assertion) else None
                it = self.item(other, fields=v.fields if v else (), label_spec=v.label_spec if v else None,
                               follows=v.follow if v else (), depth=depth + 1, path=path, type_of=v,
                               link=link, edge_props=f.edge_props)
            key = self._order_key(other, it, f)
            items.append((key, it))
        items.sort(key=lambda kv: kv[0])
        items = [it for _, it in items]
        return items if f.limit is None else items[:f.limit]

    def _order_key(self, other, it: dict, f: Follow):
        if f.order_by is None:
            return ((0, it['label'] or '') if it['label'] is not None else (1, ''), it['id'] or '')
        v = self.first(other, f.order_by)
        if v is None:
            return (1, (0, 0, ''), it['id'] or '')  # missing sorts last either way
        k = _sort_key(v)
        if f.desc:
            k = _Desc(k)
        return (0, k, it['id'] or '')

    def project(self, obj, view: View | None) -> dict:
        if view is None:
            view = self.select_view(obj)
        if view is None:
            return self.item(obj, fields=(), label_spec=None, follows=(), depth=0, path=frozenset())
        return self.item(obj, fields=view.fields, label_spec=view.label_spec, follows=view.follow,
                         depth=0, path=frozenset(), type_of=view)


class _Desc:
    '''Inverts the ordering of a wrapped sort key (for `order_by = "-field"`).'''
    __slots__ = ('k',)

    def __init__(self, k):
        self.k = k

    def __lt__(self, other):
        return other.k < self.k

    def __eq__(self, other):
        return isinstance(other, _Desc) and self.k == other.k


def _node_of(g: graph, node_or_id):
    '''A node/assertion object as given, else the node with that id (`KeyError` if absent).'''
    if isinstance(node_or_id, (node, assertion)):
        return node_or_id
    return g[node_or_id]


def project(g: graph, node_or_id, specs, *, spec: View | Mapping | None = None,
            predicates: Mapping[str, Callable] | None = None, max_depth: int = DEFAULT_MAX_DEPTH,
            raw: bool = False, registry: InterpretationRegistry = DEFAULT) -> dict:
    '''
    Project a node (object or id) of `g` through the view specs (`load()` output, or raw
    data `load()` accepts). The first spec, in declaration order, whose `type` matches one of
    the node's types (and whose `when` hook, if any, returns true) is used; `spec=` forces one.
    A node matching no spec projects to just its id.

    - `predicates`: resolves string `when` names to `callable(node, graph) -> bool`.
    - `max_depth`: follow steps from the root to expand (edge-on-edge follows count one more
      step); beyond it an item is marked `truncated: 'depth'`. A node already on the current
      path isn't re-expanded (`truncated: 'cycle'`).
    - `raw`: keep every value as its stored string, ignoring `@as`.
    '''
    views = load(specs)
    p = _Projector(g, views, predicates=predicates, max_depth=max_depth, raw=raw, registry=registry)
    obj = _node_of(g, node_or_id)
    return p.project(obj, None if spec is None else load(spec)[0])


# --- store-backed projection ----------------------------------------------------------

@dataclass
class _Tracker:
    loaded: set = dc_field(default_factory=set)
    inbound_done: set = dc_field(default_factory=set)
    missing: set = dc_field(default_factory=set)
    missing_inbound: set = dc_field(default_factory=set)

    def need(self, nid) -> None:
        if nid not in self.loaded:
            self.missing.add(nid)

    def need_inbound(self, nid, label) -> None:
        if (nid, label) not in self.inbound_done:
            self.missing_inbound.add((nid, label))


def _static_reach(follows: Iterable[Follow], max_depth: int) -> int:
    '''Follow steps a spec certainly takes (a show-less follow's onward reach is data-dependent).'''
    best = 0
    for f in follows:
        onward = _static_reach(f.follow, max_depth) if f.show is not None else 0
        if not f.inbound:
            best = max(best, 1 + onward)
    return min(best, max_depth)


async def project_from_store(store, name, node_id, specs, *, prefixes: Mapping[str, str] | None = None,
                             spec: View | Mapping | None = None, predicates: Mapping[str, Callable] | None = None,
                             max_depth: int = DEFAULT_MAX_DEPTH, raw: bool = False,
                             registry: InterpretationRegistry = DEFAULT) -> dict:
    '''
    `project`, fetching only the neighborhood the view needs instead of `get()`-ing the whole
    graph. On an `AssertionStore` (SQLite, PostgreSQL): one `subgraph(roots={node_id},
    hops=<the spec's outbound reach>)`, then — only for what that didn't cover (inbound
    follows, edge-on-edge targets, show-less follows reaching further) — a few more small
    fetches, one round per missing level: `match(label=, target=)` for inbound links and
    `subgraph(hops=0)` for missing nodes. The result equals `project` over the whole graph.
    Other stores (the filesystem) fall back to `get()`.

    `prefixes`: resolve the spec's CURIEs/bare names. Optional — stores keep each graph's
    prefixes (from `put`), and those are used; prefixes passed here take precedence over stored
    ones (a clash warns). Raises `KeyError` if the node is absent.
    '''
    from onya.store.base import AssertionStore  # lazy: keep onya.view importable without the store layer

    views = load(specs)
    forced = None if spec is None else load(spec)[0]
    nid = I(str(node_id))

    if not isinstance(store, AssertionStore):
        g = await store.get(name)
        g.add_prefixes(prefixes)
        return project(g, nid, views, spec=forced, predicates=predicates, max_depth=max_depth,
                       raw=raw, registry=registry)

    local = graph(prefixes=prefixes)
    tracker = _Tracker()
    root_views = (forced,) if forced is not None else views
    hops = max((_static_reach(v.follow, max_depth) for v in root_views), default=0)
    local.union(await store.subgraph(name, {nid}, hops=hops))
    tracker.loaded = {k for k, n in local.nodes.items() if n.types or n.properties or n.edges} | {nid}
    if nid not in local.nodes:
        raise KeyError(str(nid))

    while True:
        tracker.missing, tracker.missing_inbound = set(), set()
        p = _Projector(local, views, predicates=predicates, max_depth=max_depth, raw=raw,
                       registry=registry, tracker=tracker)
        result = p.project(local[nid], forced)
        if not tracker.missing and not tracker.missing_inbound:
            return result
        fetch = set(tracker.missing)
        for target, label in tracker.missing_inbound:
            async for origin, _rel, _tgt, _ann in store.match(name, label=label, target=target):
                if origin not in tracker.loaded:
                    fetch.add(origin)
            tracker.inbound_done.add((target, label))
        if fetch:
            local.union(await store.subgraph(name, fetch, hops=0))
            tracker.loaded |= fetch


# --- debugging ------------------------------------------------------------------------

def to_text(proj: dict, indent: str = '  ') -> str:
    '''A plain indented rendering of a `project` result, for debugging and tests.'''
    lines: list[str] = []

    def val(v):
        return ', '.join(map(str, v)) if isinstance(v, list) else str(v)

    def emit(it: dict, depth: int):
        pad = indent * depth
        head = it.get('label') or it.get('id')
        if it.get('type'):
            head = f'{head} [{it["type"]}]'
        if it.get('truncated'):
            head = f'{head} (…{it["truncated"]})'
        lines.append(pad + head)
        for k, v in it.get('fields', ()):
            lines.append(f'{pad}{indent}{k}: {val(v)}')
        for k, v in it.get('edge', ()):
            if isinstance(v, list) and v and isinstance(v[0], dict):
                lines.append(f'{pad}{indent}~{k}:')
                for sub in v:
                    emit(sub, depth + 2)
            else:
                lines.append(f'{pad}{indent}~{k}: {val(v)}')
        for k, v in it.items():
            if k in RESERVED_KEYS:
                continue
            lines.append(f'{pad}{indent}{k}:' + ('' if v else ' (none)'))
            for sub in v:
                emit(sub, depth + 2)

    emit(proj, 0)
    return '\n'.join(lines)
