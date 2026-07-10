# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.postgres
'''
PostgreSQL store backend (asyncpg), extras-gated: ``pip install "onya[postgres]"``.

asyncpg is imported **lazily inside** ``from_url`` so that neither importing this module nor
using another backend requires it; its absence raises an instructive ``ImportError``.

One relational projection serves every supported server. The backend probes
``server_version`` at connect time:

- **>= 19**: additionally creates/refreshes the two SQL/PGQ property graph definitions
  (``onya_base``, ``onya_reified``) and the returned store also satisfies ``GraphQueryStore``.
- **17-18**: identical behavior minus PGQ; no user-facing fork.

Concurrency posture: a connection pool (``asyncpg.create_pool``); each write runs in its own
transaction. This is the networked, multi-writer, production backend.

The schema, skeleton hashing, and the interp-amendment decision are shared with SQLite in
``onya.store._relational``; only the I/O plumbing (async, ``$n`` placeholders, ``RETURNING``)
differs here. SQLite is the tested proving ground for the projection's semantics.
'''

from __future__ import annotations

from amara.iri import I

from onya.graph import GraphMergeError, graph
from onya.store._relational import (
    POSTGRES, SCHEMA_VERSION, SKELETON_HASH_VERSION, classify_anonymous, ddl_statements,
    iter_records, skeleton_hash,
)
from onya.store.exceptions import UnknownSchemaVersion

_IMPORT_HINT = 'PostgreSQL support requires: pip install "onya[postgres]"'


class PostgresStore:
    '''PostgreSQL-backed store. Satisfies ``GraphStore`` + ``AssertionStore``.'''

    dialect = POSTGRES

    def __init__(self, pool, server_major: int):
        self._pool = pool
        self.server_major = server_major
        # Fast path (INSERT ... ON CONFLICT DO SELECT) is a PG19 feature; feature-detected by
        # version, not try/except. Currently the portable case-analysis path is used on every
        # version pending PG19-final verification (see the filed follow-up); the flag is kept so
        # the fast path can be switched on without re-plumbing.
        self._supports_upsert_select = server_major >= 19

    # --- construction / lifecycle ---------------------------------------------------

    @classmethod
    async def from_url(cls, url: str) -> 'PostgresStore':
        try:
            import asyncpg
        except ImportError as e:  # extras-gated; feature-detected, not silently degraded
            raise ImportError(_IMPORT_HINT) from e

        pool = await asyncpg.create_pool(url)
        async with pool.acquire() as conn:
            ver = conn.get_server_version()
            major = ver[0] if isinstance(ver, tuple) else ver.major
            async with conn.transaction():
                await _ensure_schema(conn)
                if major >= 19:
                    await _ensure_pgq(conn)
        store_cls = PostgresGraphQueryStore if major >= 19 else cls
        return store_cls(pool, major)

    async def __aenter__(self) -> 'PostgresStore':
        return self

    async def __aexit__(self, *exc) -> None:
        await self._pool.close()

    async def _reset_for_tests(self) -> None:
        '''Empty every graph (used by the conformance fixture); leaves the schema in place.'''
        async with self._pool.acquire() as conn:
            await conn.execute('DELETE FROM onya_graph')

    # --- GraphStore -----------------------------------------------------------------

    async def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        g.validate_id_space()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _write_graph(conn, str(name), g, merge=merge)

    async def get(self, name: I | str) -> graph:
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                raise KeyError(str(name))
            return await _build_graph(conn, gpk)

    async def drop(self, name: I | str) -> None:
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                raise KeyError(str(name))
            await conn.execute('DELETE FROM onya_graph WHERE graph_pk = $1', gpk)

    async def names(self):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch('SELECT name FROM onya_graph ORDER BY name')
        for r in rows:
            yield I(r['name'])

    # --- AssertionStore -------------------------------------------------------------

    async def match(self, name: I | str, origin: I | str | None = None,
                    label: I | str | None = None):
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                return
            sql = (
                'SELECT a.assertion_pk, a.kind, a.label, a.value, ti.id AS target_id, i.id AS origin_id'
                ' FROM onya_assertion a'
                ' JOIN onya_node n ON n.node_pk = a.origin_node'
                ' JOIN onya_ident i ON i.ident_pk = n.ident_pk'
                ' LEFT JOIN onya_ident ti ON ti.ident_pk = a.target_ident'
                ' WHERE a.graph_pk = $1'
            )
            args = [gpk]
            if origin is not None:
                args.append(str(origin))
                sql += f' AND i.id = ${len(args)}'
            if label is not None:
                args.append(str(label))
                sql += f' AND a.label = ${len(args)}'
            rows = await conn.fetch(sql, *args)
            results = []
            for r in rows:
                target = r['value'] if r['kind'] == 'P' else I(r['target_id'])
                ann_rows = await conn.fetch(
                    "SELECT label, value FROM onya_assertion WHERE origin_assertion = $1 AND kind = 'P'",
                    r['assertion_pk'])
                annotations = {I(a['label']): a['value'] for a in ann_rows}
                results.append((I(r['origin_id']), I(r['label']), target, annotations))
        for row in results:
            yield row

    async def subgraph(self, name: I | str, roots: set[I | str], hops: int = 1) -> graph:
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                raise KeyError(str(name))
            included: set[int] = set()
            frontier: set[int] = set()
            for rid in {str(r) for r in roots}:
                ipk = await conn.fetchval(
                    'SELECT ident_pk FROM onya_ident WHERE graph_pk = $1 AND id = $2', gpk, rid)
                if ipk is not None:
                    included.add(ipk)
                    frontier.add(ipk)
            for _ in range(max(hops, 0)):
                if not frontier:
                    break
                rows = await conn.fetch(
                    'SELECT DISTINCT target_ident FROM onya_edge_hop WHERE source_ident = ANY($1::bigint[])',
                    list(frontier))
                targets = {r['target_ident'] for r in rows}
                frontier = targets - included
                included |= frontier
            return await _build_graph(conn, gpk, node_idents=included)

    async def add(self, name, origin, label, target_or_value, *, kind,
                  interp=None, id_=None) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _add_one(conn, str(name), str(origin), str(label), str(target_or_value),
                               kind=kind, interp=None if interp is None else str(interp),
                               id_=None if id_ is None else str(id_))

    async def remove(self, name, origin, label, target_or_value, *, kind) -> None:
        payload = str(target_or_value)
        sk = skeleton_hash(kind, str(origin), str(label), payload)
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                return
            await conn.execute(
                'DELETE FROM onya_assertion WHERE graph_pk = $1 AND skeleton_hash = $2'
                ' AND ident_pk IS NULL', gpk, sk)


class PostgresGraphQueryStore(PostgresStore):
    '''PostgreSQL >= 19: additionally satisfies ``GraphQueryStore`` (SQL/PGQ escape hatch).'''

    async def graph_table(self, sql: str, *args) -> list[tuple]:
        '''
        Execute a user query containing ``GRAPH_TABLE(...)`` against this store's PGQ graph
        definitions. The SQL is the caller's own; ``$n`` parameters are supported. Onya does
        not wrap PGQ in a query language — this is the documented escape hatch.
        '''
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [tuple(r) for r in rows]


# --- schema / PGQ -------------------------------------------------------------------

async def _ensure_schema(conn) -> None:
    for stmt in ddl_statements(POSTGRES):
        await conn.execute(stmt)
    for key, expected in (('schema_version', SCHEMA_VERSION),
                          ('skeleton_hash_version', SKELETON_HASH_VERSION)):
        val = await conn.fetchval('SELECT value FROM onya_meta WHERE key = $1', key)
        if val is None:
            await conn.execute('INSERT INTO onya_meta (key, value) VALUES ($1, $2)', key, expected)
        elif val != expected:
            raise UnknownSchemaVersion(found=val, expected=expected)


async def _ensure_pgq(conn) -> None:
    '''
    Create/refresh the two SQL/PGQ property graph definitions over the existing tables
    (PostgreSQL >= 19). ``onya_edge_hop`` is a driver-maintained companion table rather than a
    view because whether the initial PG19 PGQ accepts views/predicated subsets as element
    tables is unverified — the companion table is the version that certainly works. Verifying
    the view-backed alternative against PG19-final is tracked as a follow-up issue.
    '''
    await conn.execute('DROP PROPERTY GRAPH IF EXISTS onya_base')
    await conn.execute('''
        CREATE PROPERTY GRAPH onya_base
          VERTEX TABLES (onya_ident LABEL resource PROPERTIES (id))
          EDGE TABLES (
            onya_edge_hop
              SOURCE KEY (source_ident) REFERENCES onya_ident (ident_pk)
              DESTINATION KEY (target_ident) REFERENCES onya_ident (ident_pk)
              LABEL asserted PROPERTIES (label))
    ''')
    await conn.execute('DROP PROPERTY GRAPH IF EXISTS onya_reified')
    await conn.execute('''
        CREATE PROPERTY GRAPH onya_reified
          VERTEX TABLES (
            onya_ident LABEL resource PROPERTIES (id),
            onya_assertion LABEL assertion PROPERTIES (label, kind))
          EDGE TABLES (
            onya_edge_hop
              SOURCE KEY (source_ident) REFERENCES onya_ident (ident_pk)
              DESTINATION KEY (target_ident) REFERENCES onya_ident (ident_pk)
              LABEL hop PROPERTIES (label))
    ''')


# --- write path (async mirror of _relational.write_graph) ---------------------------

async def _graph_pk(conn, name: str):
    return await conn.fetchval('SELECT graph_pk FROM onya_graph WHERE name = $1', name)


async def _get_or_create_graph(conn, name: str) -> int:
    pk = await _graph_pk(conn, name)
    if pk is not None:
        return pk
    return await conn.fetchval('INSERT INTO onya_graph (name) VALUES ($1) RETURNING graph_pk', name)


async def _get_or_create_ident(conn, gpk: int, idv: str) -> int:
    pk = await conn.fetchval('SELECT ident_pk FROM onya_ident WHERE graph_pk = $1 AND id = $2', gpk, idv)
    if pk is not None:
        return pk
    return await conn.fetchval(
        'INSERT INTO onya_ident (graph_pk, id) VALUES ($1, $2) RETURNING ident_pk', gpk, idv)


async def _get_or_create_node(conn, ident_pk: int) -> int:
    pk = await conn.fetchval('SELECT node_pk FROM onya_node WHERE ident_pk = $1', ident_pk)
    if pk is not None:
        return pk
    return await conn.fetchval(
        'INSERT INTO onya_node (ident_pk) VALUES ($1) RETURNING node_pk', ident_pk)


async def _insert_assertion(conn, gpk, rec, origin_node, origin_assertion, target_ident, ident_pk) -> int:
    apk = await conn.fetchval(
        'INSERT INTO onya_assertion'
        ' (graph_pk, kind, origin_node, origin_assertion, label, target_ident, value,'
        '  ident_pk, interp, skeleton_hash)'
        ' VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING assertion_pk',
        gpk, rec.kind, origin_node, origin_assertion, rec.label, target_ident,
        rec.value, ident_pk, rec.interp, rec.skeleton)
    return apk


async def _maybe_edge_hop(conn, apk, rec, source_ident, target_ident) -> None:
    if rec.kind != 'E' or source_ident is None:
        return
    await conn.execute(
        'INSERT INTO onya_edge_hop (assertion_pk, source_ident, target_ident, label)'
        ' VALUES ($1,$2,$3,$4)', apk, source_ident, target_ident, rec.label)


async def _write_graph(conn, name: str, g, *, merge: bool) -> None:
    if not merge:
        await conn.execute('DELETE FROM onya_graph WHERE name = $1', name)
    gpk = await _get_or_create_graph(conn, name)

    ident_cache: dict[str, int] = {}

    async def ensure_ident(idv: str) -> int:
        idv = str(idv)
        pk = ident_cache.get(idv)
        if pk is None:
            pk = await _get_or_create_ident(conn, gpk, idv)
            ident_cache[idv] = pk
        return pk

    node_ident: dict[str, int] = {}
    node_pk_by_id: dict[str, int] = {}
    for nid, n in g.nodes.items():
        ipk = await ensure_ident(nid)
        node_ident[str(nid)] = ipk
        npk = await _get_or_create_node(conn, ipk)
        node_pk_by_id[str(nid)] = npk
        for t in sorted(n.types, key=str):
            await conn.execute(
                'INSERT INTO onya_node_type (node_pk, type_iri) VALUES ($1,$2)'
                ' ON CONFLICT DO NOTHING', npk, str(t))

    for nid, n in g.nodes.items():
        src_ident = node_ident[str(nid)]
        pk_by_obj: dict[int, int] = {}
        for rec in iter_records(n):
            if rec.parent is None:
                origin_node, origin_assertion, edge_source = node_pk_by_id[str(nid)], None, src_ident
            else:
                parent_pk = pk_by_obj.get(id(rec.parent))
                if parent_pk is None:
                    continue
                origin_node, origin_assertion, edge_source = None, parent_pk, None
            target_ident = await ensure_ident(rec.target_id) if rec.kind == 'E' else None

            if rec.explicit_id is not None:
                apk = await _put_identified(conn, gpk, rec, origin_node, origin_assertion,
                                            target_ident, ensure_ident, edge_source)
            else:
                apk = await _put_anonymous(conn, gpk, rec, origin_node, origin_assertion,
                                           target_ident, edge_source)
            if apk is not None:
                pk_by_obj[id(rec.obj)] = apk


async def _put_identified(conn, gpk, rec, origin_node, origin_assertion, target_ident,
                          ensure_ident, edge_source):
    aipk = await ensure_ident(rec.explicit_id)
    row = await conn.fetchrow(
        'SELECT assertion_pk, skeleton_hash, interp FROM onya_assertion'
        ' WHERE graph_pk = $1 AND ident_pk = $2', gpk, aipk)
    if row is not None:
        apk, sk_db, interp_db = row['assertion_pk'], bytes(row['skeleton_hash']), row['interp']
        if sk_db != rec.skeleton:
            raise GraphMergeError(
                f'Assertion id {rec.explicit_id!r} has a stored skeleton differing from the '
                f'incoming one (Rule 1: same id implies same skeleton).')
        if interp_db is not None and rec.interp is not None and interp_db != rec.interp:
            raise GraphMergeError(
                f'Assertion id {rec.explicit_id!r} carries a differing interpretation: '
                f'{interp_db!r} vs {rec.interp!r}.')
        if interp_db is None and rec.interp is not None:
            await conn.execute('UPDATE onya_assertion SET interp = $1 WHERE assertion_pk = $2',
                               rec.interp, apk)
        return apk
    apk = await _insert_assertion(conn, gpk, rec, origin_node, origin_assertion, target_ident, aipk)
    await _maybe_edge_hop(conn, apk, rec, edge_source, target_ident)
    return apk


async def _put_anonymous(conn, gpk, rec, origin_node, origin_assertion, target_ident, edge_source):
    rows = await conn.fetch(
        'SELECT assertion_pk, interp FROM onya_assertion'
        ' WHERE graph_pk = $1 AND skeleton_hash = $2 AND ident_pk IS NULL', gpk, rec.skeleton)
    existing = [(r['assertion_pk'], r['interp']) for r in rows]
    action, pk, set_interp = classify_anonymous(existing, rec.interp)
    if action == 'drop':
        return None
    if action == 'merge':
        if set_interp is not None:
            await conn.execute('UPDATE onya_assertion SET interp = $1 WHERE assertion_pk = $2',
                               set_interp, pk)
        return pk
    apk = await _insert_assertion(conn, gpk, rec, origin_node, origin_assertion, target_ident, None)
    await _maybe_edge_hop(conn, apk, rec, edge_source, target_ident)
    return apk


async def _add_one(conn, name, origin, label, payload, *, kind, interp, id_):
    from onya.store._relational import ARecord
    gpk = await _get_or_create_graph(conn, name)
    o_ipk = await _get_or_create_ident(conn, gpk, origin)
    o_npk = await _get_or_create_node(conn, o_ipk)
    sk = skeleton_hash(kind, origin, label, payload)
    target_ident = await _get_or_create_ident(conn, gpk, payload) if kind == 'E' else None
    rec = ARecord(obj=object(), parent=None, kind=kind, label=label,
                  target_id=payload if kind == 'E' else None,
                  value=None if kind == 'E' else payload, interp=interp,
                  explicit_id=id_, skeleton=sk)

    async def ensure_ident(idv):
        return await _get_or_create_ident(conn, gpk, str(idv))

    if id_ is not None:
        await _put_identified(conn, gpk, rec, o_npk, None, target_ident, ensure_ident, o_ipk)
    else:
        await _put_anonymous(conn, gpk, rec, o_npk, None, target_ident, o_ipk)


# --- build a graph from rows (async mirror of sqlite._build_graph) ------------------

async def _build_graph(conn, gpk: int, node_idents: set[int] | None = None) -> graph:
    g = graph()

    ident_rows = await conn.fetch('SELECT ident_pk, id FROM onya_ident WHERE graph_pk = $1', gpk)
    id_by_ipk = {r['ident_pk']: r['id'] for r in ident_rows}

    node_rows = await conn.fetch(
        'SELECT n.node_pk, n.ident_pk FROM onya_node n'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = $1', gpk)
    id_by_npk: dict[int, str] = {}
    wanted_npks: set[int] = set()
    for r in node_rows:
        if node_idents is not None and r['ident_pk'] not in node_idents:
            continue
        nid = id_by_ipk[r['ident_pk']]
        id_by_npk[r['node_pk']] = nid
        wanted_npks.add(r['node_pk'])
        if nid not in g.nodes:
            g.node(I(nid))
    for npk in wanted_npks:
        trows = await conn.fetch('SELECT type_iri FROM onya_node_type WHERE node_pk = $1', npk)
        for tr in trows:
            g[I(id_by_npk[npk])].types.add(I(tr['type_iri']))

    arows = await conn.fetch(
        'SELECT assertion_pk, kind, origin_node, origin_assertion, label, target_ident,'
        ' value, ident_pk, interp FROM onya_assertion WHERE graph_pk = $1 ORDER BY assertion_pk', gpk)
    obj_by_apk: dict[int, object] = {}
    pending_edges: list[tuple[object, int]] = []
    for r in arows:
        if r['origin_node'] is not None:
            if node_idents is not None and r['origin_node'] not in wanted_npks:
                continue
            origin = g[I(id_by_npk[r['origin_node']])]
        else:
            origin = obj_by_apk.get(r['origin_assertion'])
            if origin is None:
                continue
        if r['kind'] == 'P':
            obj = origin.add_property(I(r['label']), r['value'])
        else:
            obj = origin.add_edge(I(r['label']), None)
            pending_edges.append((obj, r['target_ident']))
        if r['interp'] is not None:
            obj.interp = I(r['interp'])
        if r['ident_pk'] is not None:
            g.register_assertion_id(I(id_by_ipk[r['ident_pk']]), obj)
        obj_by_apk[r['assertion_pk']] = obj

    for edge_obj, tident in pending_edges:
        tid = id_by_ipk[tident]
        if tid in g.assertion_ids:
            edge_obj.target = g.assertion_ids[tid]
        elif tid in g.nodes:
            edge_obj.target = g[tid]
        else:
            edge_obj.target = g.node(I(tid))
    return g


# --- canned transitive-reachability helper ------------------------------------------

async def reachable(store: PostgresStore, name: I | str, root: I | str,
                    label: I | str, max_hops: int) -> list:
    '''
    Transitive reachability from ``root`` following edges of ``label``, up to ``max_hops``,
    via a recursive CTE over ``onya_edge_hop``. PGQ in PG19 is fixed-depth only, so transitive
    traversals still mean a recursive CTE at this layer (quantified path patterns are expected
    in a later PostgreSQL release). Returns the list of reachable node ids (IRIs).
    '''
    async with store._pool.acquire() as conn:
        gpk = await _graph_pk(conn, str(name))
        if gpk is None:
            raise KeyError(str(name))
        rows = await conn.fetch(
            '''
            WITH RECURSIVE reach(ident_pk, depth) AS (
                SELECT ident_pk, 0 FROM onya_ident WHERE graph_pk = $1 AND id = $2
                UNION
                SELECT h.target_ident, r.depth + 1
                FROM reach r
                JOIN onya_edge_hop h ON h.source_ident = r.ident_pk AND h.label = $3
                WHERE r.depth < $4
            )
            SELECT DISTINCT i.id
            FROM reach r JOIN onya_ident i ON i.ident_pk = r.ident_pk
            WHERE r.depth > 0
            ''',
            gpk, str(root), str(label), int(max_hops))
    return [I(r['id']) for r in rows]
