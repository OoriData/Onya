# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.circum
'''
Circumstances: the data that surrounds the things a knowledge graph is about, kept in tables.

A graph is the place for what a thing *is*; what is true of it this quarter, in volume, belongs in a
relational table. `onya.circum` projects a graph into such tables, and (later) reads them back at
the edge of a graph. This is the projection half. The tables are derived from the graph and can be
rebuilt from it; the graph stays the source of truth. See `doc/design-circum.md`.

    p = from_shapes(g, 'https://example.org/Person')    # columns from the class's @Property shapes
    print(ddl(p))                                       # CREATE TABLE ...
    report = await materialize('sqlite:circ.db', p, g)  # create, then insert / update / delete rows
    print(report)                                       # 5 inserted, 0 updated, 0 unchanged, ...

A projection can be written by hand (`Projection([Table(...)])`), but is normally derived from the
shape layer (`onya.shape`). Every `materialize` records the content digest of the graph it projected
(`onya.digest`) in `onya_circum_runs`, so "which graph version produced these tables" is a lookup.
'''

import asyncio
import contextlib
import datetime as _dt
import graphlib
import inspect
import re
import sqlite3
import warnings
from dataclasses import dataclass, field
from decimal import Decimal

from amara.iri import I

from onya.digest import digest
from onya.graph import graph
from onya.interp import DEFAULT, InterpretationError
from onya.locations import describe
from onya.ordering import OrderingError, ordered
from onya.shape import Finding, PropertyShape, Shapes, load_shapes
from onya.terms import (
    ONYA_ASOF, ONYA_CIRCUMQUERY, ONYA_CLASS, ONYA_COLUMN, ONYA_DOCUMENT, ONYA_INTERP, ONYA_LABEL, ONYA_METHOD_REL,
    ONYA_PROPERTY, ONYA_QUERYDETAIL, ONYA_RETENTION, ONYA_SENSITIVITY, ONYA_SIDECAR, ONYA_SOURCE_REL, ONYA_SYSTEM,
    ONYA_SYSTEM_REL, ONYA_TABLE,
)

RUNS_TABLE = 'onya_circum_runs'
UPDATED = 'updated'  # every projected table keeps one: when the row was last inserted or changed
# Interpretation IRI -> column type. Anything else (and no interpretation at all) is `text`: never a guess.
TYPES = {
    str(ONYA_INTERP('integer')): 'integer',
    str(ONYA_INTERP('number')): 'numeric',
    str(ONYA_INTERP('datetime')): 'timestamptz',
    str(ONYA_INTERP('boolean')): 'boolean',
}
_SQLITE_TYPES = {'text': 'TEXT', 'integer': 'INTEGER', 'numeric': 'NUMERIC', 'timestamptz': 'TEXT',
                 'boolean': 'INTEGER'}
_SAFE_NAME = re.compile(r'^[a-z_][a-z0-9_]*$')
# Enough of the SQL reserved words that a label or class can plausibly be called, to quote them
_RESERVED = frozenset('''all and any as asc between by case check column constraint create default desc distinct
    do else end except false for foreign from group having in index intersect into is join key like limit not
    null offset on or order primary references select table then to true union unique user using value values
    when where with'''.split())


class CircumError(ValueError):
    '''
    The projection can't be built or written. `problems` lists everything wrong, each naming its node
    (and line, when the graph tracked locations), so one run reports them all. Raised before anything
    is written.
    '''
    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        shown = '; '.join(self.problems[:3])
        more = f' (and {len(self.problems) - 3} more)' if len(self.problems) > 3 else ''
        super().__init__(shown + more)


# --- the projection -------------------------------------------------------------------

@dataclass
class Column:
    '''
    name -- the column name
    type -- `text`, `integer`, `numeric`, `timestamptz` or `boolean`
    kind -- `id` (the node's IRI), `value` (a property), `edge` (a link's target id), `ordinal` (an `@ordering` stamp),
        `qualifier` (a nested value that tells a child table's rows apart: part of its key) or `attribute` (a
        nested value that rides along with the row)
    label -- the assertion label IRI the column is read from (None for `id`)
    ref -- for an edge: the table whose `id` it references, if there is exactly one
    interp -- the interpretation IRI the value is read with, when the column's type came from one
    one_of -- the allowed values (a CHECK), for a single text value
    '''
    name: str
    type: str = 'text'
    nullable: bool = True
    kind: str = 'value'
    label: str | None = None
    ref: str | None = None
    interp: str | None = None
    one_of: tuple = ()
    array: bool = False
    ordered: bool = False  # an array column holds its values in `@ordering` order


@dataclass
class Table:
    '''
    A root table has one row per node of class `cls` (and of `also`, its subclasses), and one column per
    single-valued property. A child table (`parent` set) has one row per value or edge of one label of
    those nodes: its columns are the owner's `id`, then a value or edge column, then its `qualifier` and
    `attribute` columns, or an `ordinal` if the label is ordered. `required` means every owner must have at least
    one row.
    '''
    name: str
    cls: str
    columns: list
    label: str | None = None  # child table: the label whose values or edges are its rows
    parent: str | None = None
    ordered: bool = False
    required: bool = False
    also: frozenset = frozenset()

    @property
    def classes(self) -> frozenset:
        return frozenset({self.cls}) | self.also

    @property
    def key(self) -> tuple:
        '''
        Names of the primary key columns: `id`; or owner plus ordinal (ordered), owner plus qualifiers (when it
        has any: the same value can recur under another qualifier), or owner plus value.
        '''
        if self.parent is None:
            return (self.columns[0].name,)
        if self.ordered:
            return (self.columns[0].name, next(c.name for c in self.columns if c.kind == 'ordinal'))
        quals = tuple(c.name for c in self.columns if c.kind == 'qualifier')
        return (self.columns[0].name, *quals) if quals else (self.columns[0].name, self.columns[1].name)

    @property
    def extras(self) -> list:
        '''The qualifier and attribute columns (empty for a table that has none).'''
        return [c for c in self.columns if c.kind in ('qualifier', 'attribute')]


@dataclass
class Projection:
    '''Tables, plus a `name` that identifies the projection in the bookkeeping table (default: the root classes).'''
    tables: list
    name: str | None = None
    foreign_keys: bool = True

    def __post_init__(self):
        if self.name is None:
            self.name = ','.join(sorted({t.cls for t in self.tables if t.parent is None}))
        names = [t.name for t in self.tables]
        for n in {n for n in names if names.count(n) > 1}:
            raise CircumError(f'two tables are named {n!r}')
        for t in self.tables:
            if UPDATED in {c.name for c in t.columns}:
                raise CircumError(f'table {t.name} has a column named {UPDATED!r}, which every projected table '
                                  'keeps for the row\'s timestamp; rename it with @column')

    def ordered_tables(self) -> list:
        '''The tables in the order they can be created: every table after the ones its foreign keys reference.'''
        deps = {t.name: set() for t in self.tables}
        for t in self.tables:
            if t.parent:
                deps[t.name].add(t.parent)
            deps[t.name] |= {c.ref for c in t.columns if c.ref}
            deps[t.name].discard(t.name)  # a table may reference itself (a deferred FK handles the row order)
        unknown = {d for ds in deps.values() for d in ds} - set(deps)
        if unknown:
            raise CircumError(f'a column references {sorted(unknown)}, which is not in the projection')
        ts = graphlib.TopologicalSorter()
        for name in sorted(deps):
            ts.add(name, *sorted(deps[name]))
        try:
            order = list(ts.static_order())
        except graphlib.CycleError as e:
            raise CircumError(f'tables reference each other in a cycle {e.args[1]}; '
                              'build the Projection with foreign_keys=False') from e
        by_name = {t.name: t for t in self.tables}
        return [by_name[n] for n in order]


def _local(iri) -> str:
    return re.split(r'[/#]', str(iri).rstrip('/#'))[-1]


def _snake(name: str) -> str:
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name)
    s = re.sub(r'[^A-Za-z0-9_]+', '_', s).strip('_').lower()
    return s if s and not s[0].isdigit() else f'_{s}'


def single_valued(shapes) -> frozenset:
    '''
    The label IRIs whose `@cardinality` allows at most one value: what `store.overlay(single_cardinality=)`
    wants, so that a later layer *replaces* a single-valued label rather than adding a second value.
    `shapes` is a `Shapes` or a graph holding the declarations.
    '''
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(shapes)
    return frozenset(k for k, p in sh.properties.items() if p.cardinality and p.cardinality[1] == 1)


def from_shapes(g, cls, *, shapes=None, array_columns: bool = False) -> Projection:
    '''
    Derive the projection for class `cls` (and the classes its edges point at) from the `@Property`
    shapes that apply to it, in `shapes` (a graph or `Shapes`) or else in `g` itself.

    A property with `@as` becomes a column typed from it (`integer`, `number` -> numeric, `datetime`
    -> timestamptz, `boolean`; anything else, and no `@as`, is text). `@cardinality` 1 is `NOT NULL`;
    `0..1`, or none declared, is nullable. A maximum above one becomes a child table, or with
    `array_columns` (PostgreSQL only) an array column. `@range -> C` becomes a foreign key column to
    C's table, which is included too; `@ordered: true` adds an `ordinal`. A property with no
    `@appliesTo` names no class, so it gives no column. `@table` and `@column` on a declaration
    override the derived names. A `@oneOf` becomes a CHECK.

    A property with several values may declare `@qualifier -> q` (a nested label that tells its values apart)
    and `@attribute -> a` (one that rides along): each becomes a column of its child table, typed from its
    own `@as`. The qualifiers, not the value, are then the key, so the same value can recur under another
    qualifier. A qualifier a value lacks is the empty string (text qualifiers only); an attribute it lacks is NULL.
    '''
    sg = shapes if isinstance(shapes, graph) else g
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(sg)
    todo_root = str(g.resolve(cls))  # names the projection, as the root class
    tables, todo, seen = [], [todo_root], set()
    while todo:
        c = todo.pop(0)
        if c in seen:
            continue
        seen.add(c)
        root, children = _class_tables(sg, sh, c, array_columns)
        tables += [root, *children]
        todo += [x for t in (root, *children) for x in _range_classes(sh, t) if x not in seen]
    # edge columns reference the table of their class: resolve class ids to table names
    names = {t.cls: t.name for t in tables if t.parent is None}
    for t in tables:
        for col in t.columns:
            if col.kind == 'edge':
                col.ref = names.get(col.ref) if col.ref in names else None
    return Projection(tables, name=todo_root)


def _range_classes(sh, table) -> list:
    return [c.ref for c in table.columns if c.kind == 'edge' and c.ref]


def _name_of(sg, ident, term, default) -> str:
    n = sg.nodes.get(sg.resolve(ident)) if hasattr(sg, 'nodes') else None
    found = n.values(term) if n is not None else []
    return found[0] if found else default


def _extra_columns(sg, sh, p, pid) -> list:
    '''The qualifier columns, then the attribute columns, a property's declarations ask for.'''
    out = []
    for kind, ids in (('qualifier', p.qualifiers), ('attribute', p.attributes)):
        for qid in ids:
            q = sh.properties.get(qid)
            if q is None:
                raise CircumError(f'{_local(pid)}: @{kind} -> {_local(qid)}, which is not declared as a @Property')
            if q.range:
                raise CircumError(f'{_local(pid)}: @{kind} {_local(qid)} has a @range: a {kind} is a value')
            name = _name_of(sg, qid, ONYA_COLUMN, _snake(q.label or _local(qid)))
            ctype = TYPES.get(str(q.interp), 'text') if q.interp is not None else 'text'
            out.append(Column(name, ctype, kind == 'attribute', kind, qid, None,
                              str(q.interp) if q.interp is not None else None))
    return out


def _class_tables(sg, sh, cls, array_columns):
    '''The root table for `cls`, and a child table for each of its properties with several values.'''
    tname = _name_of(sg, cls, ONYA_TABLE, _snake(_local(cls)))
    ancestors = sh.closure([cls])
    descendants = frozenset(k for k in sh.classes if cls in sh.closure([k])) - {cls}
    cols = [Column('id', 'text', False, 'id')]
    children = []
    for pid in sorted(sh.properties):
        p = sh.properties[pid]
        if not {str(a) for a in p.applies_to} & ancestors:
            continue
        cname = _name_of(sg, pid, ONYA_COLUMN, _snake(p.label or _local(pid)))
        lo, hi = p.cardinality if p.cardinality else (0, 1)
        if p.range:
            # one range class: a foreign key to its table (resolved to a table name once all classes are read)
            ref = next(iter(p.range)) if len(p.range) == 1 else None
            proto = Column(f'{cname}_id', 'text', lo == 0, 'edge', pid, ref)
        else:
            ctype = TYPES.get(str(p.interp), 'text') if p.interp is not None else 'text'
            proto = Column(cname, ctype, lo == 0, 'value', pid, None, str(p.interp) if p.interp is not None else None,
                           tuple(sorted(p.one_of)) if hi == 1 and ctype == 'text' else ())
        extras = _extra_columns(sg, sh, p, pid)
        if extras and (hi == 1 or p.ordered or (array_columns and not p.range)):
            raise CircumError(f'{_local(pid)}: @qualifier and @attribute need a property that holds several values '
                              'in a child table (a @cardinality above 1, not ordered, and no array_columns)')
        if hi == 1:
            cols.append(proto)
        elif array_columns and not p.range:
            proto.array, proto.ordered = True, p.ordered
            cols.append(proto)
        else:
            payload = Column('target_id' if p.range else 'value', proto.type, False, proto.kind, pid, proto.ref,
                             proto.interp)
            kids = [Column(f'{tname}_id', 'text', False, 'id'), payload]
            kids += extras
            if p.ordered:
                kids.append(Column('ordinal', 'integer', False, 'ordinal'))
            children.append(Table(f'{tname}_{cname}', cls, kids, pid, tname, p.ordered, lo >= 1,
                                  frozenset(descendants)))
    root = Table(tname, cls, cols, also=frozenset(descendants))
    for t in children:
        t.also = root.also
    check_names(root, children)
    return root, children


def check_names(root, children):
    for t in (root, *children):
        names = [c.name for c in t.columns]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise CircumError(f'table {t.name} would have more than one column named {dup}; rename one with @column')


# --- DDL ------------------------------------------------------------------------------

def _q(name: str) -> str:
    return name if _SAFE_NAME.match(name) and name not in _RESERVED else '"' + name.replace('"', '""') + '"'


def _type(col, dialect: str) -> str:
    if col.array:
        if dialect != 'postgres':
            raise CircumError(f'array column {col.name}: arrays need PostgreSQL (use a child table for sqlite)')
        return f'{col.type}[]'
    return col.type if dialect == 'postgres' else _SQLITE_TYPES[col.type]


def statements(p: Projection, dialect: str = 'postgres', *, if_not_exists: bool = False) -> list:
    '''One `CREATE TABLE` per table, in an order where each follows the tables its foreign keys name.'''
    if dialect not in ('postgres', 'sqlite'):
        raise ValueError(f"dialect must be 'postgres' or 'sqlite', not {dialect!r}")
    ine = 'IF NOT EXISTS ' if if_not_exists else ''
    out = []
    for t in p.ordered_tables():
        lines = []
        for c in t.columns:
            line = f'{_q(c.name)} {_type(c, dialect)}' + ('' if c.nullable else ' NOT NULL')
            lines.append(line)
        lines.append(f'{_q(UPDATED)} ' + ('TEXT' if dialect == 'sqlite' else 'timestamptz'))
        lines.append(f'PRIMARY KEY ({", ".join(map(_q, t.key))})')
        if p.foreign_keys:
            if t.parent:
                lines.append(f'FOREIGN KEY ({_q(t.columns[0].name)}) REFERENCES {_q(t.parent)} (id) '
                             'ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED')
            lines += [f'FOREIGN KEY ({_q(c.name)}) REFERENCES {_q(c.ref)} (id) DEFERRABLE INITIALLY DEFERRED'
                      for c in t.columns if c.ref]
        for c in t.columns:
            if c.one_of:
                vals = ', '.join("'" + v.replace("'", "''") + "'" for v in c.one_of)
                lines.append(f'CHECK ({_q(c.name)} IN ({vals}))')
        out.append(f'CREATE TABLE {ine}{_q(t.name)} (\n    ' + ',\n    '.join(lines) + '\n);')
    return out


def ddl(p: Projection, dialect: str = 'postgres') -> str:
    '''The projection's `CREATE TABLE` statements as one script (`dialect` is `postgres` or `sqlite`).'''
    return '\n\n'.join(statements(p, dialect))


# --- rows -----------------------------------------------------------------------------

def _utc(v) -> _dt.datetime:
    '''A date or datetime as an aware UTC datetime: a column of timestamptz has no naive values.'''
    if not isinstance(v, _dt.datetime):
        v = _dt.datetime(v.year, v.month, v.day)
    return v.replace(tzinfo=_dt.timezone.utc) if v.tzinfo is None else v.astimezone(_dt.timezone.utc)


def _coerce(col, value):
    '''A Python value from the interpretation, shaped for the column type (or ValueError).'''
    if col.type == 'integer':
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or value != int(value):
            raise ValueError(f'{value!r} is not an integer')
        return int(value)
    if col.type == 'numeric':
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise ValueError(f'{value!r} is not a number')
        return value
    if col.type == 'timestamptz':
        if not isinstance(value, (_dt.date, _dt.datetime)):
            raise ValueError(f'{value!r} is not a date or datetime')
        return _utc(value)
    if col.type == 'boolean':
        if not isinstance(value, bool):
            raise ValueError(f'{value!r} is not a boolean')
        return value
    return value if isinstance(value, str) else str(value)


def _read(g, registry, col, a):
    '''The value of property assertion `a` for `col`: converted with its own `@as`, else the column's.'''
    iri = a.interp if a.interp is not None and a.interp in registry else col.interp
    interp = registry.get(iri) if iri is not None else None
    return _coerce(col, interp.to_python(a.value) if interp is not None else a.value)


def _claims(n, label) -> list:
    '''The distinct claims `n` makes under `label`, a value or an edge each, sorted for determinism.'''
    seen = {}
    for a in (*n.getprop(label), *n.getedge(label)):
        seen.setdefault(('e', str(a.target.id)) if hasattr(a, 'target') else ('p', a.value), a)
    return [seen[k] for k in sorted(seen)]


def rows(p: Projection, g, *, nodes=None, registry=DEFAULT) -> dict:
    '''
    `{table name: [row tuples]}` for the nodes of `g` (or just `nodes`), sorted by key. Values are Python
    values read through their interpretation (an `@as: integer` is an `int`); `timestamptz` values are
    aware UTC. Raises `CircumError`, listing every problem, for a value that is not valid for its
    column, a missing required value, a single-valued label with several values, or an edge to a node
    that is in no table.
    '''
    wanted = None if nodes is None else {str(g.resolve(n)) for n in nodes}
    out, problems = {t.name: [] for t in p.tables}, []

    def bad(n, a, label, why):
        where = describe(g.locate(a if a is not None else n)) if hasattr(g, 'locate') else ''
        problems.append(f'{n.id}: {_local(label)}: {why} {where}'.rstrip())

    def one(n, col, a):
        if hasattr(a, 'target') != (col.kind == 'edge'):
            why = 'is an edge, not a value' if hasattr(a, 'target') else 'is a value, not an edge'
            return bad(n, a, col.label, why)
        try:
            return _read(g, registry, col, a) if col.kind == 'value' else str(a.target.id)
        except (InterpretationError, ValueError) as e:
            bad(n, a, col.label, str(getattr(e, 'message', None) or e))

    for t in p.tables:
        for n in sorted(g.nodes.values(), key=lambda n: str(n.id)):
            if wanted is not None and str(n.id) not in wanted:
                continue
            if not t.classes & {str(x) for x in n.types}:
                continue
            if t.parent is None:
                row = [str(n.id)]
                for col in t.columns[1:]:
                    found = _claims(n, col.label)
                    if col.array:
                        vals = _ordered_or_sorted(n, col, found, bad) if col.ordered else found
                        row.append([v for v in (one(n, col, a) for a in vals) if v is not None])
                    elif len(found) > 1:
                        bad(n, found[1], col.label, f'{len(found)} values, but the shape allows one')
                        row.append(None)
                    elif not found:
                        if not col.nullable:
                            bad(n, None, col.label, 'required, but the node has none')
                        row.append(None)
                    else:
                        row.append(one(n, col, found[0]))
                out[t.name].append(tuple(row))
                continue
            payload = t.columns[1]
            if t.extras:
                found = [a for a in (*n.getprop(t.label), *n.getedge(t.label))]
                if t.required and not found:
                    bad(n, None, t.label, 'required (at least one), but the node has none')
                names = [c.name for c in t.columns]
                seen = {}  # key -> the row it holds
                for a in found:
                    v = one(n, payload, a)
                    if v is None:
                        continue
                    try:
                        row = (str(n.id), v, *(_nested_value(g, registry, c, a) for c in t.extras))
                    except (InterpretationError, ValueError) as e:
                        bad(n, a, t.label, str(getattr(e, 'message', None) or e))
                        continue
                    k = tuple(row[names.index(x)] for x in t.key)
                    if k not in seen:
                        seen[k] = row
                    elif seen[k] != row:  # the same key, different content: a human decides which is right
                        bad(n, a, t.label, f'conflict: {_key_text(t, k)} holds {_content(t, seen[k])} '
                                           f'and {_content(t, row)}')
                out[t.name] += list(seen.values())
                continue
            found = _claims(n, t.label)
            if t.required and not found:
                bad(n, None, t.label, 'required (at least one), but the node has none')
            if t.ordered:
                try:
                    found = ordered(n, t.label, found)
                except OrderingError as e:
                    bad(n, None, t.label, e.problem)
                    continue
            for a in found:
                v = one(n, payload, a)
                if v is not None:
                    out[t.name].append((str(n.id), v, _stamp(a)) if t.ordered else (str(n.id), v))
    for t in p.tables:
        out[t.name].sort(key=lambda r: tuple(r[[c.name for c in t.columns].index(k)] for k in t.key))
    if problems:
        raise CircumError(problems)
    if wanted is None and p.foreign_keys:
        _check_targets(p, out, g)
    return out


def _nested_value(g, registry, col, a):
    '''
    What the value assertion `a` says in qualifier or attribute column `col`: a Python value. Absent is NULL for
    an attribute, and for a text qualifier the empty string (a key can't be NULL); a typed qualifier can't be absent.
    '''
    if any(True for _ in a.getedge(col.label)):
        raise ValueError(f'{_local(col.label)} is an edge, not a value')
    found = {c.value: c for c in a.getprop(col.label)}
    if len(found) > 1:
        raise ValueError(f'{_local(col.label)} has {len(found)} different values on one value')
    if not found:
        if col.kind == 'attribute':
            return None
        if col.type == 'text':
            return ''
        raise ValueError(f'{_local(col.label)} is missing: a {col.type} qualifier is part of the key, so required')
    return _read(g, registry, col, next(iter(found.values())))


def _content(t: Table, row: tuple) -> tuple:
    '''A child row without its owner and key: the value and attributes, which are what can disagree.'''
    return tuple(v for c, v in zip(t.columns, row) if c.name not in t.key)


def _key_text(t: Table, key: tuple) -> str:
    '''`period='2026', unit='hour'`: a child table's key, past the owner, as a reader would say it.'''
    return ', '.join(f'{n}={v!r}' for n, v in zip(t.key[1:], key[1:]))


def _ordered_or_sorted(n, col, found, bad):
    try:
        return ordered(n, col.label, found)
    except OrderingError as e:
        bad(n, None, col.label, e.problem)
        return []


def _stamp(a) -> int:
    from onya.ordering import stamp_of
    return stamp_of(a)


def _check_targets(p, out, g):
    '''A foreign key to a table needs a row there: report edges to nodes that are not in it, naming the source.'''
    ids = {t.name: {r[0] for r in out[t.name]} for t in p.tables if t.parent is None}
    problems = []
    for t in p.tables:
        for i, c in enumerate(t.columns):
            if c.kind == 'edge' and c.ref in ids:
                problems += [f'{r[0]}: {_local(c.label)}: points at {r[i]}, which is not in table {c.ref}'
                             for r in out[t.name] if r[i] is not None and r[i] not in ids[c.ref]]
    if problems:
        raise CircumError(problems)


# --- backends -------------------------------------------------------------------------
# Thin on purpose: three operations and a transaction. SQLite goes through the stdlib; PostgreSQL
# through asyncpg, imported only when used (`pip install "onya[postgres]"`).

class _Sqlite:
    dialect, marker = 'sqlite', '?'

    def __init__(self, conn, lock=None):
        self.conn, self.lock = conn, lock or asyncio.Lock()

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    async def fetch(self, sql, params=()):
        return await self._run(lambda: [tuple(r) for r in self.conn.execute(sql, params).fetchall()])

    async def execute(self, sql, params=()):
        await self._run(lambda: self.conn.execute(sql, params))

    async def executemany(self, sql, rows):
        await self._run(lambda: self.conn.executemany(sql, rows))

    async def tables(self):
        return {r[0] for r in await self.fetch("SELECT name FROM sqlite_master WHERE type = 'table'")}

    async def columns(self, table):
        '''`{column name: declared type, lowercase}` of a table (empty if there is none).'''
        return {r[1]: (r[2] or '').lower() for r in await self.fetch(f'PRAGMA table_info({_q(table)})')}

    @contextlib.asynccontextmanager
    async def transaction(self):
        async with self.lock:
            await self.execute('BEGIN')
            try:
                yield
            except BaseException:
                await self.execute('ROLLBACK')
                raise
            await self.execute('COMMIT')

    def encode(self, col, v):
        if v is None:
            return None
        if col.type == 'timestamptz':
            return v.isoformat()
        if col.type == 'numeric':
            return str(v)
        return int(v) if col.type == 'boolean' else v


class _Postgres:
    dialect = 'postgres'
    marker = '$'

    def __init__(self, conn):
        self.conn = conn  # one connection for the whole call, so reads outside a transaction work too

    async def fetch(self, sql, params=()):
        return [tuple(r) for r in await self.conn.fetch(sql, *params)]

    async def execute(self, sql, params=()):
        await self.conn.execute(sql, *params)

    async def executemany(self, sql, rows):
        await self.conn.executemany(sql, rows)

    async def tables(self):
        found = await self.fetch('SELECT table_name FROM information_schema.tables '
                                 'WHERE table_schema = current_schema()')
        return {r[0] for r in found}

    async def columns(self, table):
        found = await self.fetch('SELECT column_name, data_type FROM information_schema.columns '
                                 'WHERE table_schema = current_schema() AND table_name = $1', (table,))
        return {name: kind.lower() for name, kind in found}

    @contextlib.asynccontextmanager
    async def transaction(self):
        async with self.conn.transaction():
            yield

    def encode(self, col, v):
        return v


@contextlib.asynccontextmanager
async def _target(target):
    '''Open `target` (a URL, an `onya.store` store, a `sqlite3.Connection` or an asyncpg pool) as a backend.'''
    if isinstance(target, str):
        scheme = target.partition(':')[0].lower()
        if scheme == 'sqlite':
            from onya.store.sqlite import _url_to_path
            conn = await asyncio.to_thread(lambda: sqlite3.connect(_url_to_path(target), check_same_thread=False))
            await asyncio.to_thread(lambda: conn.execute('PRAGMA foreign_keys=ON'))
            try:
                yield _Sqlite(conn)
            finally:
                await asyncio.to_thread(conn.close)
            return
        if scheme in ('postgres', 'postgresql'):
            try:
                import asyncpg
            except ImportError as e:
                raise ImportError('PostgreSQL support requires: pip install "onya[postgres]"') from e
            conn = await asyncpg.connect(target)
            try:
                yield _Postgres(conn)
            finally:
                await conn.close()
            return
        raise ValueError(f'Unknown target URL scheme {scheme!r}; known: sqlite, postgresql')
    if isinstance(target, sqlite3.Connection):
        yield _Sqlite(target)
    elif hasattr(target, '_conn') and isinstance(target._conn, sqlite3.Connection):  # an onya.store SqliteStore
        yield _Sqlite(target._conn, target._lock)
    elif hasattr(target, '_pool') or hasattr(target, 'acquire'):  # an onya.store PostgresStore, or an asyncpg pool
        async with (getattr(target, '_pool', None) or target).acquire() as conn:
            yield _Postgres(conn)
    else:
        raise TypeError(f'cannot project into {target!r}: expected a URL, an onya.store store or a connection')


# --- materialize ----------------------------------------------------------------------

@dataclass
class Report:
    '''What a `materialize` did: tables created, rows inserted / updated / left unchanged / deleted, and the
    digest of the graph it projected.'''
    created: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    graph_digest: str = ''
    tables: dict = field(default_factory=dict)  # table name -> (inserted, updated, unchanged, deleted)

    def __str__(self) -> str:
        return (f'{self.created} tables created, {self.inserted} rows inserted, {self.updated} updated, '
                f'{self.unchanged} unchanged, {self.deleted} deleted ({self.graph_digest})')


def _norm(col, v):
    '''One comparable form for a stored value and a new value alike, whichever backend stored it.'''
    if v is None:
        return None
    if col.array:
        return [_norm(Column(col.name, col.type), x) for x in v]
    if col.type == 'timestamptz':
        return _utc(_dt.datetime.fromisoformat(v) if isinstance(v, str) else v)
    if col.type == 'numeric':
        return Decimal(str(v))
    if col.type == 'boolean':
        return bool(v)
    return v


def _marks(be, n, start=1):
    return [('?' if be.marker == '?' else f'${i}') for i in range(start, start + n)]


async def materialize(target, p: Projection, g, *, nodes=None, registry=DEFAULT) -> Report:
    '''
    Write the projection of `g` into `target`: create the tables that are missing, then insert, update
    and delete rows until the tables hold exactly what `rows(p, g)` gives. A second run over an
    unchanged graph reports every row `unchanged`. It all happens in one transaction, and the rows are
    built and checked first, so a bad value (a `CircumError` naming its node and line) writes nothing.

    target -- `'sqlite:path'`, `'postgresql://...'` (asyncpg), or an open `onya.store` store, `sqlite3.Connection`
        or asyncpg pool
    nodes -- only (re)project these nodes: rows owned by other nodes are left alone, and rows owned by one of
        `nodes` that no longer exists are deleted. Pass the ids whose `onya.digest.node_digests` changed.

    Tables are created if absent and never altered. A table that no longer matches the projection (a column
    missing, extra or of another type, as after a migration or a hand-made `ALTER TABLE`) is a `CircumError`
    naming the difference, before any row is written: after changing a projection's columns, drop the tables.
    Every row inserted or changed is stamped in its `updated` column with the time of the run.
    The bookkeeping row (`onya_circum_runs`) records the digest of the *whole* graph either way.
    '''
    data = rows(p, g, nodes=nodes, registry=registry)
    wanted = None if nodes is None else {str(g.resolve(n)) for n in nodes}
    report = Report(graph_digest=digest(g))
    now = _dt.datetime.now(_dt.timezone.utc)
    async with _target(target) as be:
        async with be.transaction():
            have = await be.tables()
            for t in p.ordered_tables():
                report.created += t.name not in have
            for sql in statements(p, be.dialect, if_not_exists=True):
                await be.execute(sql)
            await be.execute(_runs_ddl(be))
            await _check_schema(be, p)
            for t in p.ordered_tables():
                stats = await _sync_table(be, t, data[t.name], wanted, now)
                report.tables[t.name] = stats
                report.inserted, report.updated, report.unchanged, report.deleted = (
                    a + b for a, b in zip((report.inserted, report.updated, report.unchanged, report.deleted), stats))
            marks = _marks(be, 7)
            await be.execute(f'INSERT INTO {RUNS_TABLE} VALUES ({", ".join(marks)})', (
                now.isoformat() if be.dialect == 'sqlite' else now, p.name, report.graph_digest,
                report.inserted, report.updated, report.unchanged, report.deleted))
    return report


def _runs_ddl(be) -> str:
    when = 'TEXT' if be.dialect == 'sqlite' else 'timestamptz'
    return (f'CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (run_at {when} NOT NULL, projection TEXT NOT NULL, '
            'graph_digest TEXT NOT NULL, inserted INTEGER NOT NULL, updated INTEGER NOT NULL, '
            'unchanged INTEGER NOT NULL, deleted INTEGER NOT NULL)')


_UPDATED_COLUMN = Column(UPDATED, 'timestamptz')
_PG_TYPES = {'text': 'text', 'integer': 'integer', 'numeric': 'numeric', 'timestamptz': 'timestamp with time zone',
             'boolean': 'boolean'}


def _stored_type(col, dialect: str) -> str:
    '''The type a backend reports for `col`'s column (`PRAGMA table_info` declared type, or `data_type`).'''
    if dialect == 'sqlite':
        return _SQLITE_TYPES[col.type].lower()
    return 'array' if col.array else _PG_TYPES[col.type]


async def _check_schema(be, p: Projection, tables=None) -> None:
    '''
    `CircumError` unless each table (of `tables`, default all) is what `p` says: every column, its `updated`,
    and nothing else, with the types `statements` gives. The tables are an agreed contract between the
    projection, `augment` and `emit`; one that a migration or a hand-made `ALTER TABLE` changed can't be
    trusted to be read or written.
    '''
    problems = []
    for t in tables or p.tables:
        found = await be.columns(t.name)
        if not found:
            problems.append(f'table {t.name} does not exist')
            continue
        want = {c.name: _stored_type(c, be.dialect) for c in t.columns}
        want[UPDATED] = _stored_type(_UPDATED_COLUMN, be.dialect)
        missing, extra = sorted(set(want) - set(found)), sorted(set(found) - set(want))
        wrong = [f'{n} is {found[n]}, expected {want[n]}' for n in sorted(set(want) & set(found))
                 if found[n] != want[n]]
        if missing or extra or wrong:
            bits = ([f'missing {missing}'] if missing else []) + ([f'unexpected {extra}'] if extra else []) + wrong
            hint = (f' (a table made before 0.6.1 has no {UPDATED!r}: it can be added with ALTER TABLE, or the '
                    'tables rebuilt)') if UPDATED in missing else ''
            problems.append(f'table {t.name} no longer follows the projection: {"; ".join(bits)}{hint}')
    if problems:
        raise CircumError(problems)


async def _sync_table(be, t: Table, new: list, wanted, now) -> tuple:
    '''Make the stored rows of `t` match `new` (for the owners in `wanted`, or all); counts of changes.'''
    names = [c.name for c in t.columns]
    cols = {c.name: c for c in t.columns}
    kix = [names.index(k) for k in t.key]
    key = lambda r: tuple(r[i] for i in kix)  # noqa: E731
    stored = {}
    for r in await be.fetch(f'SELECT {", ".join(map(_q, names))} FROM {_q(t.name)}'):
        if wanted is None or r[0] in wanted:
            stored[key(r)] = r
    ins, upd, dele, same = [], [], [], 0
    wanted_keys = {key(r) for r in new}
    for r in new:
        old = stored.get(key(r))
        if old is None:
            ins.append(r)
        elif all(_norm(cols[n], a) == _norm(cols[n], b) for n, a, b in zip(names, old, r)):
            same += 1
        else:
            upd.append(r)
    dele = [k for k in stored if k not in wanted_keys]
    enc = lambda r: tuple(be.encode(cols[n], v) for n, v in zip(names, r))  # noqa: E731
    stamp = be.encode(_UPDATED_COLUMN, now)
    nonkey = [n for n in names if n not in t.key]
    if dele:
        cond = ' AND '.join(f'{_q(k)} = {m}' for k, m in zip(t.key, _marks(be, len(t.key))))
        await be.executemany(f'DELETE FROM {_q(t.name)} WHERE {cond}', [k for k in dele])
    if upd and nonkey:
        sets = ', '.join(f'{_q(n)} = {m}' for n, m in zip([*nonkey, UPDATED], _marks(be, len(nonkey) + 1)))
        cond = ' AND '.join(f'{_q(k)} = {m}' for k, m in zip(t.key, _marks(be, len(t.key), len(nonkey) + 2)))
        await be.executemany(f'UPDATE {_q(t.name)} SET {sets} WHERE {cond}', [
            (*(enc(r)[names.index(n)] for n in nonkey), stamp, *(enc(r)[i] for i in kix)) for r in upd])
    if ins:
        await be.executemany(f'INSERT INTO {_q(t.name)} ({", ".join(map(_q, [*names, UPDATED]))}) '
                             f'VALUES ({", ".join(_marks(be, len(names) + 1))})', [(*enc(r), stamp) for r in ins])
    return len(ins), len(upd), same, len(dele)


async def last_run(target, p: Projection | str) -> dict | None:
    '''The most recent bookkeeping row for projection `p` (or its name), as a dict, or None if it never ran.'''
    name = p if isinstance(p, str) else p.name
    async with _target(target) as be:
        if RUNS_TABLE not in await be.tables():
            return None
        found = await be.fetch(f'SELECT run_at, projection, graph_digest, inserted, updated, unchanged, deleted '
                               f'FROM {RUNS_TABLE} WHERE projection = {_marks(be, 1)[0]} ORDER BY run_at DESC', (name,))
    if not found:
        return None
    keys = ('run_at', 'projection', 'graph_digest', 'inserted', 'updated', 'unchanged', 'deleted')
    return dict(zip(keys, found[0]))


# --- the read side: circumstances held elsewhere, shown in a view ----------------------------
#
# Some properties are *declared* in the graph but *held* in a sidecar (a table somewhere else). `augment`
# makes them appear in a new graph, the view, with the application's resolvers fetching the values;
# `strip` takes them out again; `emit` is the write-side twin, moving such assertions out of a graph into
# their sidecar. The graph never holds query text: `@queryDetail` is opaque to Onya, handed to the resolver.

_SIDECAR, _CIRCUMQUERY = str(ONYA_SIDECAR), str(ONYA_CIRCUMQUERY)
_DECLARATIONS = frozenset(map(str, (ONYA_CLASS, ONYA_PROPERTY, ONYA_SIDECAR, ONYA_SYSTEM, ONYA_DOCUMENT)))


class CircumAccessDenied(CircumError):
    '''A viewer is not allowed to read (or write) a sidecar. Raised before any resolver or writer runs.'''


class CircumDerivedError(CircumError):
    '''A graph holding circum-derived assertions (a view) was offered for persistence.'''


@dataclass
class CircumProperty:
    '''A `@Property` whose values are held in `sidecar`. `detail` is the nested `@queryDetail`, opaque to Onya.'''
    label: object  # the label IRI (the declaration's node id)
    sidecar: 'Sidecar'
    detail: str | None = None
    shape: PropertyShape | None = None  # what `onya.shape` makes of the same declaration


@dataclass
class Sidecar:
    '''A `@Sidecar` declaration: the catalog entry for a store of rows keyed by node IRI.'''
    id: object
    label: str | None = None
    system: object = None  # id of the `@System` it lives in
    table: str | None = None
    sensitivity: str | None = None
    retention: str | None = None
    holds: list = field(default_factory=list)  # the `CircumProperty`s that point at it (computed, never written)


@dataclass
class Declarations:
    sidecars: dict = field(default_factory=dict)  # str(id) -> Sidecar
    properties: dict = field(default_factory=dict)  # str(label IRI) -> CircumProperty
    problems: list = field(default_factory=list)  # `onya.shape.Finding`s for declarations that can't be read


def declarations(g, shapes=None) -> Declarations:
    '''Read the `@Sidecar` nodes and the `@circumQuery` of each `@Property` in `g`. Malformed ones become `problems`.'''
    out = Declarations()
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(g)
    where = getattr(g, 'locate', lambda obj: None)

    def problem(n, label, detail, assertion=None):
        out.problems.append(Finding('error', 'circum', n.id, label, detail, where(assertion or n), assertion))

    def one(n, term) -> str | None:
        found = n.values(term)
        if len(found) > 1:
            problem(n, term, f'a sidecar has at most one {_local(term)}, found {found}')
        return found[0] if found else None

    for n in g.nodes.values():
        if _SIDECAR in {str(t) for t in n.types}:
            systems = n.targets(ONYA_SYSTEM_REL)
            out.sidecars[str(n.id)] = Sidecar(n.id, one(n, ONYA_LABEL), systems[0].id if systems else None,
                                              one(n, ONYA_TABLE), one(n, ONYA_SENSITIVITY), one(n, ONYA_RETENTION))
    for n in g.nodes.values():
        queries = list(n.getedge(ONYA_CIRCUMQUERY))
        if not queries:
            continue
        if str(ONYA_PROPERTY) not in {str(t) for t in n.types}:
            problem(n, ONYA_CIRCUMQUERY, '@circumQuery belongs on a @Property declaration', queries[0])
            continue
        if len(queries) > 1:
            problem(n, ONYA_CIRCUMQUERY, f'a property has at most one @circumQuery, found {len(queries)}', queries[1])
            continue
        e = queries[0]
        sc = out.sidecars.get(str(e.target.id)) if hasattr(e.target, 'types') else None
        if sc is None:
            problem(n, ONYA_CIRCUMQUERY, f'{e.target.id} is not declared as a @Sidecar', e)
            continue
        details = e.values(ONYA_QUERYDETAIL)
        if len(details) > 1:
            problem(n, ONYA_CIRCUMQUERY, f'a @circumQuery has at most one @queryDetail, found {details}', e)
        prop = CircumProperty(n.id, sc, details[0] if details else None, sh.properties.get(str(n.id)))
        out.properties[str(n.id)] = prop
        sc.holds.append(prop)
    for sc in out.sidecars.values():
        sc.holds.sort(key=lambda p: str(p.label))
    return out


def catalog(g) -> list:
    '''Every `Sidecar` declared in `g`, in id order, with the properties each holds. `CircumError` if one is unsound.'''
    d = declarations(g)
    if d.problems:
        raise CircumError([str(f) for f in d.problems])
    return sorted(d.sidecars.values(), key=lambda s: str(s.id))


# What a resolver (or writer) is handed, and what it returns

@dataclass
class Node:
    '''A circum node: the few facts a synthesized edge target needs. `props` maps a label IRI to a value or a list.'''
    types: tuple = ()
    props: dict = field(default_factory=dict)


@dataclass
class Edge:
    '''
    A circum edge to `target` (a full IRI), with the `Node` to create when the graph doesn't have it yet.
    `qualifiers` and `attributes` map a label IRI to a text value: the nested assertions the property declares with
    `@qualifier` (they tell values apart) and `@attribute` (they ride along). `augment` writes them under the edge;
    `emit` hands them to the writer.
    '''
    target: str
    node: Node | None = None
    as_of: object = None  # a datetime, date or ISO 8601 string: when the sidecar says this was true
    qualifiers: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)


@dataclass
class Text:
    '''A circum value, with an optional interpretation IRI, and its `qualifiers` and `attributes` (see `Edge`).'''
    value: str
    as_of: object = None
    interp: object = None
    qualifiers: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)


@dataclass
class Context:
    '''
    What a resolver or writer gets besides its batch: the sidecar and `detail` (the nested `@queryDetail`)
    it was declared with, the property's `label` and `shape`, the `viewer`, and `conn`, whatever the caller
    passed to `augment` / `emit` (a connection, a pool): Onya never opens one.
    '''
    label: object
    sidecar: Sidecar
    detail: str | None
    shape: PropertyShape | None
    viewer: object = None
    conn: object = None


class Registry:
    '''
    The application's side of a circum declaration: resolvers (and writers) keyed by the property's label IRI,
    and `policy(viewer, sensitivity)`, which decides whether a viewer may reach a sidecar (None allows all).

        @registry.resolver('https://example.org/counselledBy')
        async def counselled_by(subjects, ctx): ...        # {subject IRI: [Edge | Text]}
    '''
    def __init__(self, policy=None):
        self.policy = policy
        self.resolvers: dict = {}
        self.writers: dict = {}

    def resolver(self, label):
        def register(fn):
            self.resolvers[str(label)] = fn
            return fn
        return register

    def writer(self, label):
        def register(fn):
            self.writers[str(label)] = fn
            return fn
        return register

    def allows(self, viewer, sidecar: Sidecar) -> bool:
        return self.policy is None or bool(self.policy(viewer, sidecar.sensitivity))


async def _call(fn, *args):
    result = fn(*args)
    return await result if inspect.isawaitable(result) else result


def _asof(v=None) -> str:
    '''ISO 8601 UTC, to the second, for `@asOf`: `v` a datetime, date or string; None is now.'''
    if isinstance(v, str):
        return v
    v = _dt.datetime.now(_dt.timezone.utc) if v is None else _utc(v)
    return v.isoformat(timespec='seconds').replace('+00:00', 'Z')


def _subjects(g, sh, prop: CircumProperty, ids) -> list:
    '''The node ids a circum property applies to: its `@appliesTo` classes (any node when none), within `ids`.'''
    wanted = None if ids is None else {str(g.resolve(i)) for i in ids}
    applies = prop.shape.applies_to if prop.shape else set()
    return sorted(str(n.id) for n in g.nodes.values()
                  if (wanted is None or str(n.id) in wanted)
                  and not {str(t) for t in n.types} & _DECLARATIONS
                  and (not applies or sh.closure(n.types) & applies))


def _denied(registry, viewer, plan) -> list:
    return [f'{prop.sidecar.id} (sensitivity {prop.sidecar.sensitivity!r}) is not available to this viewer; '
            f'needed by {prop.label}' for prop, _ in plan if not registry.allows(viewer, prop.sidecar)]


def _method_of(a, sids) -> bool:
    '''Does assertion `a` carry a nested `@method` edge to one of the sidecars `sids`?'''
    return any(str(m.target.id) in sids for m in a.getedge(ONYA_METHOD_REL))


def _consulted(g) -> set:
    '''Ids of the sidecars `g` says it was augmented from: a node with an `@asOf` that is `@method` -> itself.'''
    return {str(n.id) for n in g.nodes.values()
            if any(str(m.target.id) == str(n.id) for a in n.getprop(ONYA_ASOF) for m in a.getedge(ONYA_METHOD_REL))}


def asked(n) -> set:
    '''Ids of the sidecars a view looked in for node `n` (its `@asOf` marks with a nested `@method`).'''
    return {str(m.target.id) for a in n.getprop(ONYA_ASOF) for m in a.getedge(ONYA_METHOD_REL)}


def is_view(g) -> bool:
    '''Did `g` come out of `augment`? The view says so itself (see `augment`), so this survives writing it out.'''
    return bool(_consulted(g))


def _sidecar_node(view, sid):
    '''The node for sidecar `sid` in `view`; a bare one if the declarations live in another graph.'''
    sc = view.nodes.get(sid)
    if sc is None:
        sc = view.node(sid)
        sc._stub = True
    return sc


def _sidecar_ids(g, shapes=None) -> set:
    ids = _consulted(g)
    for src in (g, shapes):
        if src is not None:
            ids |= {str(n.id) for n in src.nodes.values() if _SIDECAR in {str(t) for t in n.types}}
    return ids


async def augment(g, *, registry: Registry, viewer=None, ids=None, shapes=None, on_error: str = 'raise',
                  conn=None, now=None) -> graph:
    '''
    The view of `g` with the values its sidecars hold: a **new graph** (`g` is untouched), in which every
    assertion added carries `@method -> <sidecar>` and `@asOf`. A node the view had to create also carries
    `@method` itself, so `strip(view)` can remove it whole.

    ids -- node ids to augment (default: every node a circum property applies to)
    shapes -- a graph holding the declarations, when they aren't in `g`
    on_error -- `'raise'` (default): a resolver that raises fails the whole call; `'finding'`: the view comes back
        and `view_findings(view)` says what failed
    conn -- opaque; handed to each resolver as `ctx.conn`
    now -- the `@asOf` of a value the resolver gave no time for (default: the current time)

    Each resolver is called once per property, with every subject at once. The viewer's access to each
    sidecar (`registry.policy`) is checked first, for all of them, before any resolver runs.
    '''
    if on_error not in ('raise', 'finding'):
        raise ValueError(f"on_error must be 'raise' or 'finding', not {on_error!r}")
    src = g if shapes is None else shapes
    decl = declarations(src)
    if decl.problems:
        raise CircumError([str(f) for f in decl.problems])
    sh = load_shapes(src)
    plan = []
    for prop in sorted(decl.properties.values(), key=lambda p: str(p.label)):
        subjects = _subjects(g, sh, prop, ids)
        if subjects:
            plan.append((prop, subjects))
    if denied := _denied(registry, viewer, plan):
        raise CircumAccessDenied(denied)
    if missing := [f'no resolver is registered for {prop.label} (sidecar {prop.sidecar.id})'
                   for prop, _ in plan if str(prop.label) not in registry.resolvers]:
        raise CircumError(missing)

    view = g.copy()
    view._circum_findings = []
    default_stamp = _asof(now)
    # The view is self-describing: each sidecar it consulted gets `@asOf` (when) with a nested `@method` back to
    # itself. That is how `validate` knows a missing value is a gap, and how `strip` and `store.put` know it's a view.
    for sid in sorted({p.sidecar.id for p in decl.properties.values()}):
        sc = _sidecar_node(view, sid)
        for old in [a for a in sc.getprop(ONYA_ASOF) if _method_of(a, {str(sid)})]:
            sc.remove_property(old)  # augmenting a view: this consultation replaces the earlier one
        sc.add_property(ONYA_ASOF, default_stamp).add_edge(ONYA_METHOD_REL, sc)
    done, failed = [], []  # the properties whose resolver succeeded, and those whose resolver failed
    for prop, subjects in plan:
        ctx = Context(prop.label, prop.sidecar, prop.detail, prop.shape, viewer, conn)
        try:
            found = await _call(registry.resolvers[str(prop.label)], subjects, ctx)
            _apply(view, prop, subjects, found or {}, default_stamp)
            sc = _sidecar_node(view, prop.sidecar.id)
            for subject in subjects:  # asked, whether or not a row came back: `validate` counts only these nodes
                n = view.nodes[str(subject)]
                if str(sc.id) not in asked(n):
                    n.add_property(ONYA_ASOF, default_stamp).add_edge(ONYA_METHOD_REL, sc)
            done.append(prop)
        except Exception as e:
            if on_error == 'raise':
                if isinstance(e, CircumError):
                    raise
                raise CircumError(f'{prop.label} (sidecar {prop.sidecar.id}): resolver failed: {e!r}') from e
            failed.append(prop)
            view._circum_findings.append(Finding('error', 'circum', prop.sidecar.id, prop.label,
                                                 f'resolver failed: {e!r}'))
    # The marks that say "this node was asked about" are per sidecar. If one property of a sidecar failed and
    # another succeeded, the graph can't tell them apart: `validate` knows from the findings (in memory), but a
    # view written out as text and read back would report the failed property's values as missing.
    if hit := [p for p in failed if any(d.sidecar.id == p.sidecar.id for d in done)]:
        names = ', '.join(sorted(str(p.label) for p in hit))
        warnings.warn(f'resolver failed for {names}, while another property of the same sidecar succeeded. If this '
                      'view is written out and read back, validate() will report those properties as missing for '
                      'the nodes asked about. Keep the view in memory, or treat those findings as the resolver '
                      'failure.', UserWarning, stacklevel=2)
    view.touch()
    return view


def view_findings(view) -> list:
    '''The findings `augment(..., on_error='finding')` recorded on `view`: one per resolver that failed.'''
    return list(getattr(view, '_circum_findings', ()))


def _apply(view, prop: CircumProperty, subjects, found, default_stamp) -> None:
    '''Add what a resolver returned to `view`, marking each addition as circum-derived.'''
    if stray := sorted(set(map(str, found)) - set(subjects)):
        raise CircumError(f'{prop.label} (sidecar {prop.sidecar.id}): the resolver returned rows for '
                          f'{stray[:3]}, which it was not asked about')
    sc = _sidecar_node(view, prop.sidecar.id)

    def mark(a, stamp, item=None):
        a.add_edge(ONYA_METHOD_REL, sc)
        a.add_property(ONYA_ASOF, stamp)
        for label, v in {**getattr(item, 'qualifiers', {}), **getattr(item, 'attributes', {})}.items():
            a.add_property(view.resolve(label), v)  # nested under the value, beside @method and @asOf

    def qualified(a, item) -> bool:
        '''Is `a` already the value `item` is: the same qualifiers (an authored one under another period isn't).'''
        keys = {str(view.resolve(k)) for k in item.qualifiers} | set(prop.shape.qualifiers if prop.shape else ())
        have = {str(c.label): c.value for c in a.properties if str(c.label) in keys}
        return have == {str(view.resolve(k)): v for k, v in item.qualifiers.items()}

    for subject, items in found.items():
        n = view.nodes[str(subject)]
        for item in items:
            stamp = _asof(item.as_of) if item.as_of is not None else default_stamp
            if isinstance(item, Text):
                if not any(p.value == item.value and qualified(p, item) for p in n.getprop(prop.label)):
                    mark(n.add_property(prop.label, item.value, interp=item.interp), stamp, item)  # else: authored
                continue
            tid = I(str(item.target))
            target = view.nodes.get(tid)
            if target is None or not target.declared:  # ours to make, so ours to take away again in `strip`
                target = target or view.node(tid)
                target.types |= {I(view.resolve(t)) for t in (item.node.types if item.node else ())}
                target.add_edge(ONYA_METHOD_REL, sc)
            if not any(e.target.id == tid and qualified(e, item) for e in n.getedge(prop.label)):
                mark(n.add_edge(prop.label, target), stamp, item)
            for label, values in (item.node.props if item.node else {}).items():
                label = view.resolve(label)
                for v in [values] if isinstance(values, str) else values:
                    if not any(p.value == v for p in target.getprop(label)):
                        mark(target.add_property(label, v), stamp)


def strip(g, *, shapes=None) -> graph:
    '''
    A copy of `g` with everything `augment` added taken out, so that `digest(strip(view)) == digest(g)`.
    It removes only what came in through a circum query: assertions carrying `@method` to a sidecar, and the
    nodes the view created (or, if something else still points at one, what it was given). Sidecars are
    known from the view itself, or the `@Sidecar` nodes in `g` or `shapes`.
    '''
    out = g.copy()
    sids = _sidecar_ids(g, shapes)
    created = set()
    for n in out.nodes.values():
        for e in list(n.edges):
            if e.label == ONYA_METHOD_REL and str(e.target.id) in sids:
                created.add(n.id)
                n.remove_edge(e)
    for n in out.nodes.values():
        for p in [p for p in n.properties if _method_of(p, sids)]:
            n.remove_property(p)
        for e in [e for e in n.edges if _method_of(e, sids)]:
            n.remove_edge(e)
    for nid in created:
        n = out.nodes[nid]
        if n.properties or n.edges:  # something else was written on it since: it stays as it is
            continue
        n.types.clear()
        if next(out.inbound(n), None) is None:
            del out[nid]
        else:
            n._stub = True  # still named by an edge, and says nothing else
    out.touch()
    return out


def derived(g) -> list:
    '''`'node label'` for each assertion in `g` that came from a sidecar (and each node a view created), or `[]`.'''
    sids = _sidecar_ids(g)
    if not sids:
        return []
    found = []
    for n in g.nodes.values():
        found += [f'{n.id} {e.label}' for e in n.edges if e.label == ONYA_METHOD_REL and str(e.target.id) in sids]
        found += [f'{n.id} {a.label}' for a in (*n.properties, *n.edges) if _method_of(a, sids)]
    return found


def check_persistable(g) -> None:
    '''Raise `CircumDerivedError` if `g` holds sidecar-derived assertions: a view must never be written back.'''
    if found := derived(g):
        raise CircumDerivedError(f'this graph is a circum view and would swallow its sidecar: {"; ".join(found[:3])}'
                                 f'{f" (and {len(found) - 3} more)" if len(found) > 3 else ""}. '
                                 'Call strip() on it first.')


@dataclass
class EmitReport:
    '''What `emit` did: `moved` is `(sidecar id, subject id, label)` per assertion, `review` what it left in place.'''
    moved: list = field(default_factory=list)
    review: list = field(default_factory=list)

    def __str__(self) -> str:
        return f'{len(self.moved)} moved, {len(self.review)} for review'


def _nested_of(prop: CircumProperty, a) -> tuple | None:
    '''
    `(qualifiers, attributes)`, each `{label IRI: text}`, if `a` can move to its sidecar, else None. It can if it has
    no `@id` and nothing nested but the parser's own `@source` and the qualifiers and attributes the property declares
    (each a plain value, once): removing it then takes nothing else along. Anything else nested is for a person.
    '''
    if a.id is not None:
        return None
    sh = prop.shape
    quals, attrs = set(sh.qualifiers if sh else ()), set(sh.attributes if sh else ())
    found = ({}, {})
    for c in (*a.properties, *a.edges):
        if c.label == ONYA_SOURCE_REL:
            continue
        key = str(c.label)
        where = found[0] if key in quals else found[1] if key in attrs else None
        if (where is None or key in found[0] or key in found[1] or hasattr(c, 'target') or c.id is not None
                or any(x.label != ONYA_SOURCE_REL for x in (*c.properties, *c.edges))):
            return None
        where[key] = c.value
    return found


async def emit(g, touched=None, *, registry: Registry, viewer=None, shapes=None, conn=None) -> EmitReport:
    '''
    The write-side twin of `augment`: for each touched node (ids; default every node), move the assertions
    whose label has a `@circumQuery` out of `g` and into their sidecar, through the property's registered
    writer, which receives `{subject IRI: [Edge | Text]}` as a batch and must be idempotent. **Sidecar first,
    graph second**: assertions leave `g` only after every writer has succeeded, so a failure changes nothing
    in `g`, and a retry writes the same rows again.

    `g` is edited in place; pass `g.copy()` for a dry run. Left in place, and named in `report.review`: an
    assertion with an `@id`, or with nested assertions other than the `@qualifier`s and `@attribute`s its
    property declares (those travel with the value, in `Text.qualifiers` and `Text.attributes`), and (silently)
    anything that already came from a sidecar.
    Raises `CircumAccessDenied` if the policy refuses the viewer, and `CircumError` for a circum label with
    no writer, both before anything is written.
    '''
    src = g if shapes is None else shapes
    decl = declarations(src)
    if decl.problems:
        raise CircumError([str(f) for f in decl.problems])
    wanted = None if touched is None else {str(g.resolve(i)) for i in touched}
    sids = {str(p.sidecar.id) for p in decl.properties.values()}
    report, plan = EmitReport(), []  # plan: (property, {subject: [items]}, [(node, assertion)])
    for prop in sorted(decl.properties.values(), key=lambda p: str(p.label)):
        batch, taken = {}, []
        for n in g.nodes.values():
            if (wanted is not None and str(n.id) not in wanted) or {str(t) for t in n.types} & _DECLARATIONS:
                continue
            for a in (*n.getprop(prop.label), *n.getedge(prop.label)):
                if _method_of(a, sids):
                    continue  # it came from the sidecar
                if (nested := _nested_of(prop, a)) is None:
                    report.review.append(f'{n.id}: {prop.label} has an id or nested assertions; unchanged')
                    continue
                quals, attrs = nested
                if hasattr(a, 'target'):
                    t = a.target
                    props = {str(p.label): [] for p in getattr(t, 'properties', ())}
                    for p in getattr(t, 'properties', ()):
                        props[str(p.label)].append(p.value)
                    node_ = Node(tuple(map(str, t.types)), props) if hasattr(t, 'types') else None
                    batch.setdefault(str(n.id), []).append(Edge(str(t.id), node_, qualifiers=quals, attributes=attrs))
                else:
                    batch.setdefault(str(n.id), []).append(Text(a.value, interp=a.interp, qualifiers=quals,
                                                                attributes=attrs))
                taken.append((n, a))
        if batch:
            plan.append((prop, batch, taken))
    if denied := _denied(registry, viewer, [(p, b) for p, b, _ in plan]):
        raise CircumAccessDenied(denied)
    if missing := [f'no writer is registered for {prop.label} (sidecar {prop.sidecar.id})'
                   for prop, _, _ in plan if str(prop.label) not in registry.writers]:
        raise CircumError(missing)
    for prop, batch, _ in plan:
        ctx = Context(prop.label, prop.sidecar, prop.detail, prop.shape, viewer, conn)
        try:
            await _call(registry.writers[str(prop.label)], batch, ctx)
        except Exception as e:
            raise CircumError(f'{prop.label} (sidecar {prop.sidecar.id}): writer failed: {e!r}') from e
    for prop, _, taken in plan:  # every writer succeeded: now the graph lets go
        for n, a in taken:
            (n.remove_edge if hasattr(a, 'target') else n.remove_property)(a)
            report.moved.append((str(prop.sidecar.id), str(n.id), str(prop.label)))
    return report


# --- tables as sidecars: resolvers and writers for the tables `materialize` built -----------------
#
# When a sidecar is a table the projection made, everything a resolver or writer needs is in the `Projection`:
# the table, its key, its column types and its foreign keys. SQL comes only from those names (quoted by `_q`),
# never from text in the graph (`@table`, `@column`, `@queryDetail`). Sidecars that are some other store, or
# a table somebody else built, keep hand-written resolvers.

def _places(p: Projection) -> dict:
    '''`{label IRI: [(table, column)]}` for each property the projection holds: a root column, or a child payload.'''
    found: dict = {}
    for t in p.tables:
        held = [(str(c.label), c) for c in t.columns[1:]] if t.parent is None else [(str(t.label), t.columns[1])]
        for label, col in held:
            found.setdefault(label, []).append((t, col))
    return {label: where for label, where in found.items()}


def _ambiguous(label, where):
    '''Stands in for a label held in several tables (a property shared by classes): which one is not for us to guess.'''
    names = sorted(t.name for t, _ in where)

    async def refuse(*_):
        raise CircumError(f'{label} is held in several tables {names}: write its resolver or writer by hand')
    return refuse


def _root_of(p: Projection, t: Table) -> Table:
    return t if t.parent is None else next(x for x in p.tables if x.name == t.parent)


def _check_sidecar(ctx, root: Table) -> None:
    '''The declared sidecar's `@table` must be the table the projection holds the property in.'''
    if ctx.sidecar.table is not None and ctx.sidecar.table != root.name:
        raise CircumError(f'{ctx.label}: sidecar {ctx.sidecar.id} declares @table {ctx.sidecar.table!r}, but the '
                          f'projection holds this property in {root.name!r}')


async def _fetch_in(be, t: Table, ids: list) -> list:
    '''Every row of `t` (its columns, then `updated`) whose owner is in `ids`: one query per 500, or one `ANY`.'''
    base = (f'SELECT {", ".join(map(_q, [c.name for c in t.columns] + [UPDATED]))} FROM {_q(t.name)} '
            f'WHERE {_q(t.columns[0].name)} ')
    if be.dialect == 'postgres':
        return await be.fetch(base + '= ANY($1)', (ids,))
    out = []
    for i in range(0, len(ids), 500):  # well under SQLite's limit on variables
        chunk = ids[i:i + 500]
        out += await be.fetch(base + f'IN ({", ".join("?" * len(chunk))})', tuple(chunk))
    return out


def _text_of(col, v) -> str:
    '''The text a stored value was projected from, in a form its interpretation reads back.'''
    n = _norm(Column(col.name, col.type), v)  # one element: an array column's `_norm` would split a string
    if col.type == 'timestamptz':
        return n.isoformat().replace('+00:00', 'Z')
    if col.type == 'numeric':
        return format(n, 'f')
    if col.type == 'boolean':
        return 'true' if n else 'false'
    return str(int(n)) if col.type == 'integer' else str(n)


def _resolver(p: Projection, t: Table, col: Column):
    root = _root_of(p, t)
    classes = {x.name: x.cls for x in p.tables if x.parent is None}  # table name -> class IRI
    ordinal = next((i for i, c in enumerate(t.columns) if c.kind == 'ordinal'), None)
    quals = [(i, c) for i, c in enumerate(t.columns) if c.kind == 'qualifier']
    attrs = [(i, c) for i, c in enumerate(t.columns) if c.kind == 'attribute']

    async def resolve(subjects, ctx):
        _check_sidecar(ctx, root)
        async with _target(ctx.conn) as be:
            await _check_schema(be, p, [t])
            found = await _fetch_in(be, t, [str(s) for s in subjects])
        if t.parent is None:
            at = [c.name for c in t.columns].index(col.name)
            order = lambda r: r[0]  # noqa: E731
        else:
            at = 1
            order = ((lambda r: (r[0], r[ordinal])) if ordinal is not None
                     else (lambda r: (r[0], *(str(r[i]) for i, _ in quals), str(r[1]))))
        out: dict = {}
        for r in sorted(found, key=order):
            when = _norm(_UPDATED_COLUMN, r[-1])  # the row's own time; None leaves the default
            for v in (r[at] or []) if col.array else [r[at]]:
                if v is None:
                    continue
                if col.kind == 'edge':
                    cls = classes.get(col.ref)
                    item = Edge(str(v), Node((cls,)) if cls else None, as_of=when)
                else:
                    item = Text(_text_of(col, v), as_of=when, interp=col.interp)
                # a text qualifier that is '' is "none given"; an attribute that is NULL likewise: neither is asserted
                item.qualifiers = {str(c.label): _text_of(c, r[i]) for i, c in quals if r[i] not in (None, '')}
                item.attributes = {str(c.label): _text_of(c, r[i]) for i, c in attrs if r[i] is not None}
                out.setdefault(r[0], []).append(item)
        return out
    return resolve


def table_resolvers(p: Projection) -> dict:
    '''
    `{label IRI: resolver}` for every property the projection holds in a table, to merge into a `Registry`:
    `registry.resolvers.update(table_resolvers(p))`. Each resolver reads from `ctx.conn`, which takes what
    `materialize` takes (a URL, an `onya.store` store, a `sqlite3.Connection` or an asyncpg pool), in one
    query for all the subjects. Values come back as the text the projection was built from, with the column's
    interpretation, and `@asOf` is the row's `updated`. A label held in several tables (a property shared by
    classes that have their own tables) gets a stand-in that raises `CircumError`: write that one by hand.
    A call raises `CircumError` if the sidecar's `@table` is not the table holding the property, or if the
    table no longer matches the projection.
    '''
    return {label: _resolver(p, *where[0]) if len(where) == 1 else _ambiguous(label, where)
            for label, where in _places(p).items()}


async def _missing_owners(be, root: Table, ids: list) -> set:
    return set(ids) - {r[0] for r in await _fetch_in(be, root, ids)}


def _refuse_new_rows(root: Table, missing, label) -> None:
    '''A row can only be inserted if nothing else in it is required: otherwise the node breaks its cardinality.'''
    needed = [c.name for c in root.columns[1:] if not c.nullable and str(c.label) != str(label)]
    if missing and needed:
        raise CircumError(f'{sorted(missing)[0]}{" and others" if len(missing) > 1 else ""}: no row in {root.name}, '
                          f'and a new one also needs {needed} (@cardinality 1, NOT NULL): the node does not '
                          'satisfy its shape, so there is nothing valid to insert')


def _column_value(col: Column, item, subject):
    '''What to store in `col` for a writer's `Edge` or `Text`: an id, or the value read through its interpretation.'''
    if (col.kind == 'edge') != isinstance(item, Edge):
        raise CircumError(f'{subject}: {_local(col.label)} is {"an edge" if col.kind == "edge" else "a value"} '
                          f'in the table, but the graph has {"an edge" if isinstance(item, Edge) else "a value"}')
    if col.kind == 'edge':
        return str(item.target)
    iri = item.interp if item.interp is not None and item.interp in DEFAULT else col.interp
    interp = DEFAULT.get(iri) if iri is not None else None
    try:
        return _coerce(col, interp.to_python(item.value) if interp is not None else item.value)
    except (InterpretationError, ValueError) as e:
        raise CircumError(f'{subject}: {_local(col.label)}: {getattr(e, "message", None) or e}') from e


def _extra_values(t: Table, item, subject) -> tuple:
    '''
    The values for `t`'s qualifier and attribute columns, from a writer's `item`: absent is `''` for a text
    qualifier and NULL for an attribute. A label the table has no such column for is refused, not dropped: a writer
    that was given it would otherwise lose it silently.
    '''
    given = {'qualifier': {str(k): v for k, v in item.qualifiers.items()},
             'attribute': {str(k): v for k, v in item.attributes.items()}}
    for kind, d in given.items():
        if stray := sorted(set(d) - {str(c.label) for c in t.extras if c.kind == kind}):
            raise CircumError(f'{subject}: {_local(t.label or "")}: table {t.name} has no {kind} column for '
                              f'{[_local(x) for x in stray]}')
    out = []
    for c in t.extras:
        v = given[c.kind].get(str(c.label))
        if v is None or (v == '' and c.kind == 'qualifier'):
            if c.kind == 'qualifier' and c.type != 'text':
                raise CircumError(f'{subject}: {_local(c.label)} is part of the key of {t.name} and has no value')
            out.append('' if c.kind == 'qualifier' else None)
        else:
            out.append(_column_value(c, Text(v), subject))
    return tuple(out)


async def _check_targets_exist(be, p: Projection, col: Column, ids) -> None:
    '''An edge column is a foreign key: its target needs a row in the referenced table.'''
    if col.kind != 'edge' or not col.ref or not p.foreign_keys:
        return
    ref = next(x for x in p.tables if x.name == col.ref)
    missing = await _missing_owners(be, ref, sorted(set(ids)))
    if missing:
        raise CircumError(f'{_local(col.label)} points at {sorted(missing)}, which are not in table {ref.name}')


def _writer(p: Projection, t: Table, col: Column):
    root = _root_of(p, t)

    async def write(rows, ctx):
        _check_sidecar(ctx, root)
        now = _dt.datetime.now(_dt.timezone.utc)
        async with _target(ctx.conn) as be:
            stamp = be.encode(_UPDATED_COLUMN, now)
            async with be.transaction():
                await _check_schema(be, p, [root] if t is root else [root, t])
                subjects = sorted(map(str, rows))
                values = {s: [_column_value(col, i, s) for i in rows[s]] for s in subjects}
                extras = {s: [_extra_values(t, i, s) for i in rows[s]] for s in subjects}
                await _check_targets_exist(be, p, col, [v for vs in values.values() for v in vs])
                missing = await _missing_owners(be, root, subjects)
                _refuse_new_rows(root, missing, col.label if t is root else None)
                if t.parent is None:
                    await _write_root(be, root, col, values, missing, stamp)
                elif t.extras:
                    await _write_keyed(be, root, t, values, extras, missing, stamp)
                else:
                    await _write_child(be, root, t, values, missing, stamp)
    return write


async def _write_root(be, root, col, values, missing, stamp) -> None:
    '''Set a root-table column for each subject; insert the row if the table has none. Unchanged values are left.'''
    for s, vs in values.items():
        if len(vs) > 1 and not col.array:
            raise CircumError(f'{s}: {_local(col.label)} has {len(vs)} values, but its column holds one')
    stored = {r[0]: r for r in await _fetch_in(be, root, [s for s in values if s not in missing])}
    at = [c.name for c in root.columns].index(col.name)
    ins, upd = [], []
    for s, vs in values.items():
        new = vs if col.array else vs[0]
        if s in missing:
            ins.append((s, be.encode(col, new), stamp))
        elif _norm(col, stored[s][at]) != _norm(col, new):  # idempotent: a value already there is not rewritten
            upd.append((be.encode(col, new), stamp, s))
    if upd:
        m = _marks(be, 3)
        await be.executemany(f'UPDATE {_q(root.name)} SET {_q(col.name)} = {m[0]}, {_q(UPDATED)} = {m[1]} '
                             f'WHERE {_q(root.columns[0].name)} = {m[2]}', upd)
    if ins:
        await be.executemany(f'INSERT INTO {_q(root.name)} ({_q(root.columns[0].name)}, {_q(col.name)}, '
                             f'{_q(UPDATED)}) VALUES ({", ".join(_marks(be, 3))})', ins)


async def _write_child(be, root, t, values, missing, stamp) -> None:
    '''Add the rows a child table lacks: one per (owner, value), never deleting any.'''
    if missing:  # the owners need a row of their own first
        await be.executemany(f'INSERT INTO {_q(root.name)} ({_q(root.columns[0].name)}, {_q(UPDATED)}) '
                             f'VALUES ({", ".join(_marks(be, 2))})', [(s, stamp) for s in sorted(missing)])
    col = t.columns[1]
    have = {(r[0], r[1]) for r in await _fetch_in(be, t, list(values))}
    new = [(s, be.encode(col, v), stamp) for s, vs in values.items() for v in vs
           if (s, be.encode(col, v)) not in have]
    if new:
        await be.executemany(f'INSERT INTO {_q(t.name)} ({_q(t.columns[0].name)}, {_q(col.name)}, {_q(UPDATED)}) '
                             f'VALUES ({", ".join(_marks(be, 3))})', new)


async def _write_keyed(be, root, t, values, extras, missing, stamp) -> None:
    '''
    Add the rows a qualified child table lacks, one per (owner, qualifiers). A row that is already there is left
    alone if it says the same, and is a conflict if it doesn't (a changed amount is for a person to see), as is
    one batch giving a key two different contents. Nothing is written when there is a conflict, and nothing is deleted.
    '''
    names = [c.name for c in t.columns]
    cols = {c.name: c for c in t.columns}
    kix = [names.index(k) for k in t.key]
    norm = lambda r: tuple(_norm(cols[n], v) for n, v in zip(names, r))  # noqa: E731
    have = {tuple(norm(r)[i] for i in kix): norm(r) for r in await _fetch_in(be, t, list(values))}
    new, seen, conflicts = [], {}, []
    for s in sorted(values):
        for v, ex in zip(values[s], extras[s]):
            row = (s, v, *ex)
            r = norm(row)
            k = tuple(r[i] for i in kix)
            held = seen.get(k) or have.get(k)
            if held is None:
                new.append(row)
            elif held[:len(names)] != r:
                conflicts.append(f'{s}: {_local(t.label)}: {_key_text(t, k)} holds {_content(t, held)}, '
                                 f'not {_content(t, r)}: a changed value is for a person to decide')
            seen[k] = held if held is not None else r
    if conflicts:
        raise CircumError(conflicts)
    if missing:  # the owners need a row of their own first
        await be.executemany(f'INSERT INTO {_q(root.name)} ({_q(root.columns[0].name)}, {_q(UPDATED)}) '
                             f'VALUES ({", ".join(_marks(be, 2))})', [(s, stamp) for s in sorted(missing)])
    if new:
        await be.executemany(f'INSERT INTO {_q(t.name)} ({", ".join(map(_q, [*names, UPDATED]))}) '
                             f'VALUES ({", ".join(_marks(be, len(names) + 1))})',
                             [(*(be.encode(cols[n], v) for n, v in zip(names, row)), stamp) for row in new])


def table_writers(p: Projection) -> dict:
    '''
    `{label IRI: writer}` for the properties `emit` can write into the projection's tables: the inverse of
    `table_resolvers`. A writer sets a single-valued column (or adds the missing rows of a child table),
    stamps what it changes with `updated`, is idempotent, and never deletes. A child table with `@qualifier`s
    adds a row per (owner, qualifiers), and a key that already holds a different value or attribute is a
    `CircumError` naming it (a changed amount is for a person to decide), with nothing written. A node with no
    row gets one only if every other column may be NULL; otherwise `CircumError` names the columns it would need.
    An edge to a node that has no row in the referenced table is refused. Properties whose order matters (an
    ordered child table or array) get no writer: `emit` leaves ordered values in the graph for review.
    '''
    return {label: _writer(p, *where[0]) if len(where) == 1 else _ambiguous(label, where)
            for label, where in _places(p).items() if not any(t.ordered or col.ordered for t, col in where)}
