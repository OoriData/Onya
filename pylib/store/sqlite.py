# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.sqlite
'''
SQLite store backend — stdlib ``sqlite3``, zero added dependencies (not extras-gated;
``pip install onya`` includes it).

Concurrency posture: a single writer connection, serialized. The connection is opened with
``check_same_thread=False`` and every access is guarded by an ``asyncio.Lock`` and runs
through ``asyncio.to_thread`` — so it is used from at most one thread at a time and never
blocks the event loop. ``PRAGMA journal_mode=WAL`` and ``PRAGMA foreign_keys=ON`` are set at
open. This is a solid single-process backend; for networked, multi-writer concurrency use
PostgreSQL.

Implements ``GraphStore`` and ``AssertionStore``. The schema, skeleton hashing, and
write-path merge algorithm are shared with PostgreSQL in ``onya.store._relational``.
'''

from __future__ import annotations

import asyncio
import sqlite3

from amara.iri import I

from onya.graph import graph
from onya.store import _relational as rel
from onya.store._relational import Dialect, SQLITE

_BATCH = 512  # fetchmany batch size for streaming match()


def _url_to_path(url: str) -> str:
    raw = url.partition(':')[2]
    if raw == ':memory:' or raw == '':
        return ':memory:'
    if raw.startswith('//'):   # sqlite:///abs.db -> /abs.db ; sqlite://rel -> rel
        raw = raw[2:]
    return raw or ':memory:'


class SqliteStore:
    '''A SQLite database holding many named graphs. Satisfies ``GraphStore`` + ``AssertionStore``.'''

    dialect: Dialect = SQLITE

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = asyncio.Lock()

    # --- construction / lifecycle ---------------------------------------------------

    @classmethod
    async def from_url(cls, url: str) -> 'SqliteStore':
        path = _url_to_path(url)

        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA foreign_keys=ON')
            cur = conn.cursor()
            rel.ensure_schema(cur, cls.dialect)
            conn.commit()
            return conn

        conn = await asyncio.to_thread(_open)
        return cls(conn)

    async def __aenter__(self) -> 'SqliteStore':
        return self

    async def __aexit__(self, *exc) -> None:
        await asyncio.to_thread(self._conn.close)

    async def _run(self, fn, *args):
        '''Serialize access to the single connection and run ``fn(conn, *args)`` off-loop.'''
        async with self._lock:
            return await asyncio.to_thread(fn, self._conn, *args)

    # --- GraphStore -----------------------------------------------------------------

    async def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        g.validate_id_space()  # node-id vs assertion-id collision -> AssertionIdConflict

        def _put(conn):
            cur = conn.cursor()
            try:
                rel.write_graph(cur, str(name), g, merge=merge, dialect=self.dialect)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        await self._run(_put)

    async def get(self, name: I | str) -> graph:
        def _get(conn):
            cur = conn.cursor()
            gpk = _graph_pk(cur, str(name))
            if gpk is None:
                raise KeyError(str(name))
            return _build_graph(cur, gpk)

        return await self._run(_get)

    async def drop(self, name: I | str) -> None:
        def _drop(conn):
            cur = conn.cursor()
            gpk = _graph_pk(cur, str(name))
            if gpk is None:
                raise KeyError(str(name))
            cur.execute('DELETE FROM onya_graph WHERE graph_pk = ?', (gpk,))
            conn.commit()

        await self._run(_drop)

    async def names(self):
        def _names(conn):
            return [r[0] for r in conn.execute('SELECT name FROM onya_graph ORDER BY name')]

        for name in await self._run(_names):
            yield I(name)

    # --- AssertionStore -------------------------------------------------------------

    async def match(self, name: I | str, origin: I | str | None = None,
                    label: I | str | None = None):
        rows = await self._run(_match_blocking, str(name),
                               None if origin is None else str(origin),
                               None if label is None else str(label))
        for r in rows:
            yield r

    async def subgraph(self, name: I | str, roots: set[I | str], hops: int = 1) -> graph:
        root_ids = {str(r) for r in roots}
        return await self._run(_subgraph_blocking, str(name), root_ids, int(hops))

    async def add(self, name: I | str, origin: I | str, label: I | str, target_or_value,
                  *, kind: str, interp: I | str | None = None, id_: I | str | None = None) -> None:
        def _add(conn):
            cur = conn.cursor()
            try:
                _add_blocking(cur, str(name), str(origin), str(label), target_or_value,
                              kind=kind, interp=None if interp is None else str(interp),
                              id_=None if id_ is None else str(id_))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        await self._run(_add)

    async def remove(self, name: I | str, origin: I | str, label: I | str, target_or_value,
                     *, kind: str) -> None:
        def _remove(conn):
            cur = conn.cursor()
            _remove_blocking(cur, str(name), str(origin), str(label), target_or_value, kind=kind)
            conn.commit()

        await self._run(_remove)


# --- blocking query/reconstruction helpers ------------------------------------------

def _graph_pk(cur, name: str):
    cur.execute('SELECT graph_pk FROM onya_graph WHERE name = ?', (name,))
    row = cur.fetchone()
    return row[0] if row else None


def _build_graph(cur, gpk: int, node_idents: set[int] | None = None) -> graph:
    '''
    Reconstruct a graph from its relational rows. When ``node_idents`` is given, only those
    node idents are materialized as full nodes; edge targets outside the set become bare
    (dangling) nodes, exactly as the parser represents an undescribed target.
    '''
    g = graph()

    # idents: ident_pk -> id
    cur.execute('SELECT ident_pk, id FROM onya_ident WHERE graph_pk = ?', (gpk,))
    id_by_ipk = {ipk: idv for ipk, idv in cur.fetchall()}

    # nodes (node_pk -> id) and their types
    cur.execute(
        'SELECT n.node_pk, n.ident_pk FROM onya_node n'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = ?',
        (gpk,),
    )
    node_rows = cur.fetchall()
    id_by_npk: dict[int, str] = {}
    wanted_npks: set[int] = set()
    for npk, ipk in node_rows:
        if node_idents is not None and ipk not in node_idents:
            continue
        nid = id_by_ipk[ipk]
        id_by_npk[npk] = nid
        wanted_npks.add(npk)
        if nid not in g.nodes:
            g.node(I(nid))
    for npk in wanted_npks:
        cur.execute('SELECT type_iri FROM onya_node_type WHERE node_pk = ?', (npk,))
        for (t,) in cur.fetchall():
            g[I(id_by_npk[npk])].types.add(I(t))

    # assertions in pk order (parents precede children, matching the write path)
    if node_idents is None:
        cur.execute(
            'SELECT assertion_pk, kind, origin_node, origin_assertion, label, target_ident,'
            ' value, ident_pk, interp FROM onya_assertion WHERE graph_pk = ? ORDER BY assertion_pk',
            (gpk,),
        )
    else:
        # scope to assertions whose top-level origin node is in the wanted set (children follow
        # via origin_assertion, which appears later in pk order)
        cur.execute(
            'SELECT assertion_pk, kind, origin_node, origin_assertion, label, target_ident,'
            ' value, ident_pk, interp FROM onya_assertion WHERE graph_pk = ? ORDER BY assertion_pk',
            (gpk,),
        )
    obj_by_apk: dict[int, object] = {}
    pending_edges: list[tuple[object, int]] = []
    for (apk, kind, onode, oassert, label, tident, value, ident_pk, interp) in cur.fetchall():
        if onode is not None:
            if node_idents is not None and onode not in wanted_npks:
                continue
            origin = g[I(id_by_npk[onode])]
        else:
            origin = obj_by_apk.get(oassert)
            if origin is None:  # parent filtered out (subgraph scope) — skip descendant
                continue
        if kind == 'P':
            obj = origin.add_property(I(label), value)
        else:
            obj = origin.add_edge(I(label), None)
            pending_edges.append((obj, tident))
        if interp is not None:
            obj.interp = I(interp)
        if ident_pk is not None:
            g.register_assertion_id(I(id_by_ipk[ident_pk]), obj)
        obj_by_apk[apk] = obj

    # resolve edge targets: identified assertion, existing node, else a bare (dangling) node
    for edge_obj, tident in pending_edges:
        tid = id_by_ipk[tident]
        if tid in g.assertion_ids:
            edge_obj.target = g.assertion_ids[tid]
        elif tid in g.nodes:
            edge_obj.target = g[tid]
        else:
            edge_obj.target = g.node(I(tid))
    return g


def _annotations(cur, assertion_pk: int) -> dict:
    '''Direct child properties of an assertion, as a ``{label: value}`` dict (match() shape).'''
    cur.execute(
        'SELECT label, value FROM onya_assertion'
        " WHERE origin_assertion = ? AND kind = 'P'",
        (assertion_pk,),
    )
    return {I(label): value for label, value in cur.fetchall()}


def _match_blocking(conn, name: str, origin: str | None, label: str | None) -> list:
    cur = conn.cursor()
    gpk = _graph_pk(cur, name)
    if gpk is None:
        return []
    sql = (
        'SELECT a.assertion_pk, a.kind, a.label, a.value, ti.id, i.id'
        ' FROM onya_assertion a'
        ' JOIN onya_node n ON n.node_pk = a.origin_node'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk'
        ' LEFT JOIN onya_ident ti ON ti.ident_pk = a.target_ident'
        ' WHERE a.graph_pk = ?'
    )
    params: list = [gpk]
    if origin is not None:
        sql += ' AND i.id = ?'
        params.append(origin)
    if label is not None:
        sql += ' AND a.label = ?'
        params.append(label)
    cur.execute(sql, params)
    out: list = []
    while True:
        batch = cur.fetchmany(_BATCH)
        if not batch:
            break
        for (apk, kind, lbl, value, target_id, origin_id) in batch:
            target = value if kind == 'P' else I(target_id)
            out.append((I(origin_id), I(lbl), target, _annotations(cur, apk)))
    return out


def _subgraph_blocking(conn, name: str, root_ids: set[str], hops: int) -> graph:
    cur = conn.cursor()
    gpk = _graph_pk(cur, name)
    if gpk is None:
        raise KeyError(name)
    # resolve root ids to node idents
    included: set[int] = set()
    frontier: set[int] = set()
    for rid in root_ids:
        cur.execute('SELECT ident_pk FROM onya_ident WHERE graph_pk = ? AND id = ?', (gpk, rid))
        row = cur.fetchone()
        if row is not None:
            included.add(row[0])
            frontier.add(row[0])
    for _ in range(max(hops, 0)):
        if not frontier:
            break
        placeholders = ','.join('?' * len(frontier))
        cur.execute(
            f'SELECT DISTINCT target_ident FROM onya_edge_hop WHERE source_ident IN ({placeholders})',
            tuple(frontier),
        )
        targets = {r[0] for r in cur.fetchall()}
        frontier = targets - included
        included |= frontier
    return _build_graph(cur, gpk, node_idents=included)


# --- single-assertion add/remove (AssertionStore) -----------------------------------

def _add_blocking(cur, name, origin, label, target_or_value, *, kind, interp, id_):
    rel.ensure_schema(cur, SQLITE)
    gpk = rel._get_or_create_graph(cur, name)
    o_ipk = rel._get_or_create_ident(cur, gpk, origin)
    o_npk = rel._get_or_create_node(cur, o_ipk)
    payload = str(target_or_value)
    sk = rel.skeleton_hash(kind, origin, label, payload)
    target_ident = rel._get_or_create_ident(cur, gpk, payload) if kind == 'E' else None
    rec = rel.ARecord(obj=object(), parent=None, kind=kind, label=label,
                      target_id=payload if kind == 'E' else None,
                      value=None if kind == 'E' else payload, interp=interp,
                      explicit_id=id_, skeleton=sk)
    if id_ is not None:
        rel._put_identified(cur, gpk, rec, o_npk, None, target_ident,
                            lambda idv: rel._get_or_create_ident(cur, gpk, idv), o_ipk)
    else:
        rel._put_anonymous(cur, gpk, rec, o_npk, None, target_ident, o_ipk)


def _remove_blocking(cur, name, origin, label, target_or_value, *, kind):
    gpk = _graph_pk(cur, name)
    if gpk is None:
        return
    payload = str(target_or_value)
    sk = rel.skeleton_hash(kind, str(origin), str(label), payload)
    cur.execute(
        'DELETE FROM onya_assertion WHERE graph_pk = ? AND skeleton_hash = ? AND ident_pk IS NULL',
        (gpk, sk),
    )
