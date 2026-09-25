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

import logging
import re

from amara.iri import I

from onya.graph import GraphMergeError, edge, graph, warn_prefix_clashes
from onya.util import namespace_for_curie
from onya.query import DEFAULT_MIN_SCORE, SearchHit, normalize as query_normalize, rank, score_candidates
from onya.store import _relational as rel
from onya.store._relational import (
    POSTGRES, SCHEMA_VERSION, SKELETON_HASH_VERSION, classify_anonymous, ddl_statements,
    iter_records, skeleton_hash,
)
from onya.store.exceptions import StoreError, UnknownSchemaVersion

_IMPORT_HINT = 'PostgreSQL support requires: pip install "onya[postgres]"'

logger = logging.getLogger(__name__)


class PostgresStore:
    '''PostgreSQL-backed store. Satisfies ``GraphStore`` + ``AssertionStore`` + ``OverlayReadStore``
    + ``SearchStore`` (``pg_trgm``-indexed when the extension is available).'''

    dialect = POSTGRES

    def __init__(self, pool, server_major: int, *, has_trgm: bool = False):
        self._pool = pool
        self.server_major = server_major
        self.has_trgm = has_trgm  # pg_trgm available -> indexed search; else in-process fallback
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
                has_trgm = await _ensure_search(conn)
                has_pgq = await _ensure_pgq(conn) if major >= 19 else False
        store_cls = PostgresGraphQueryStore if has_pgq else cls
        return store_cls(pool, major, has_trgm=has_trgm)

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
                clashes = await _write_graph(conn, str(name), g, merge=merge)
        warn_prefix_clashes(clashes, stacklevel=2)

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
                    label: I | str | None = None, where=None, *, target: I | str | None = None):
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
            if target is not None:
                args.append(str(target))
                sql += f" AND a.kind = 'E' AND ti.id = ${len(args)}"
            rows = await conn.fetch(sql, *args)
            results = []
            for r in rows:
                if where is not None and not rel.where_matches_values(
                        await _nested_prop_values(conn, r['assertion_pk'], str(where[0])), where):
                    continue
                target = r['value'] if r['kind'] == 'P' else I(r['target_id'])
                ann_rows = await conn.fetch(
                    "SELECT label, value FROM onya_assertion WHERE origin_assertion = $1 AND kind = 'P'",
                    r['assertion_pk'])
                annotations = {I(a['label']): a['value'] for a in ann_rows}
                results.append((I(r['origin_id']), I(r['label']), target, annotations))
        for row in results:
            yield row

    # --- OverlayReadStore -------------------------------------------------------------

    async def union(self, names) -> graph:
        async with self._pool.acquire() as conn:
            gpks = await _resolve_graph_pks(conn, [str(n) for n in names])
            return await _with_prefixes(conn, await _build_union(conn, gpks), gpks)

    async def match_across(self, names, origin: I | str | None = None,
                           label: I | str | None = None, where=None):
        '''
        Built over ``select()`` rather than ``match()`` so ``where=`` can walk each
        candidate's own nested properties recursively (``rel.where_matches_object``) --
        ``match()``'s tuple projection only exposes direct-child annotations, which would
        silently miss e.g. `@confidence` nested under `@method`.
        '''
        async with self._pool.acquire() as conn:
            gpks = await _resolve_graph_pks(conn, [str(n) for n in names])
            g = await _build_union(conn, gpks)
        o = I(origin) if origin is not None else None
        lbl = I(label) if label is not None else None
        for a in g.select(origin=o, label=lbl):
            if not rel.where_matches_object(a, where):
                continue
            target = a.target.id if isinstance(a, edge) else a.value
            annotations = {p.label: p.value for p in a.properties}
            yield (a.origin.id, a.label, target, annotations)

    async def subgraph_across(self, names, roots: set[I | str], hops: int = 1) -> graph:
        async with self._pool.acquire() as conn:
            gpks = await _resolve_graph_pks(conn, [str(n) for n in names])
            g = await _build_union(conn, gpks)
            pmaps = [await _read_prefixes(conn, gpk) for gpk in gpks]
        out = rel.extract_subgraph(g, {str(r) for r in roots}, int(hops))
        for pmap in pmaps:
            out.add_prefixes(pmap)
        return out

    async def overlay(self, names, *, single_cardinality=frozenset(), key=None,
                      precedence=None, prefer_confidence: bool = False):
        str_names = [str(n) for n in names]
        async with self._pool.acquire() as conn:
            gpks = await _resolve_graph_pks(conn, str_names)
            gpk_to_name = dict(zip(gpks, str_names))
            is_single = rel.normalize_cardinality_predicate(single_cardinality)
            resolved_key = key if key is not None else rel.make_overlay_key(
                precedence=[str(p) for p in precedence] if precedence is not None else None,
                prefer_confidence=prefer_confidence)
            idents, nodes, node_types, assertions = await _fetch_overlay_rows(conn, gpk_to_name)
            pmaps = [await _read_prefixes(conn, gpk) for gpk in gpks]
        g, conflicts = rel.build_overlay(idents, nodes, node_types, assertions, is_single=is_single,
                                         key=resolved_key)
        for pmap in pmaps:
            g.add_prefixes(pmap)
        return g, conflicts

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


    # --- SearchStore ------------------------------------------------------------------

    async def search(self, name: I | str, query: str, *, labels=None, types=None, limit=None,
                     min_score: float = DEFAULT_MIN_SCORE, per_node: bool = True, normalize=None,
                     similarity=None) -> list:
        '''
        With ``pg_trgm`` (and the default normalization): tiers computed in SQL against
        ``onya_normalize(value)`` — exact ``=``, prefix/word via ``LIKE`` patterns, fuzzy via
        the ``%`` / ``<%`` trigram operators with thresholds set to ``min_score`` — all served
        by the GIN trigram index, so no graph is loaded. Scores: 1.0 for exact, ``similarity``
        for prefix/word, ``greatest(similarity, word_similarity)`` for fuzzy.

        Trigram scores are not difflib/rapidfuzz scores: non-fuzzy hits and tiers match the
        other backends, but fuzzy-tier inclusion near ``min_score`` and fuzzy-tier order can
        differ (see ``SearchStore``). Without ``pg_trgm``, or given a custom ``normalize`` or
        ``similarity``, the label/type-filtered property rows are instead ranked in-process
        with ``onya.query``'s scorer — unindexed, but identical to an in-memory search.
        '''
        lbls = None if labels is None else [str(x) for x in labels]
        typs = None if types is None else [str(t) for t in types]
        async with self._pool.acquire() as conn:
            gpk = await _graph_pk(conn, str(name))
            if gpk is None:
                return []
            if not self.has_trgm or normalize is not None or similarity is not None:  # in-process path
                rows = await _search_candidates(conn, gpk, lbls, typs)
                cands = ((I(r['node_id']), I(r['label']), r['value'], None, None) for r in rows)
                hits = score_candidates(query, cands, min_score=min_score,
                                        normalize=normalize or query_normalize, similarity=similarity)
                return rank(hits, per_node=per_node, limit=limit)
            async with conn.transaction():
                rows = await _search_trgm(conn, gpk, query, lbls, typs, min_score)
        hits = (SearchHit(I(r['node_id']), I(r['label']), r['value'], r['tier'], float(r['score']))
                for r in rows if r['tier'] != 'fuzzy' or r['score'] >= min_score)
        return rank(hits, per_node=per_node, limit=limit)

    async def nodes_by_type(self, name: I | str, type_iri: I | str):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT i.id FROM onya_node_type nt'
                ' JOIN onya_node n ON n.node_pk = nt.node_pk'
                ' JOIN onya_ident i ON i.ident_pk = n.ident_pk'
                ' JOIN onya_graph g ON g.graph_pk = i.graph_pk'
                ' WHERE g.name = $1 AND nt.type_iri = $2 ORDER BY i.id',
                str(name), str(type_iri))
        for r in rows:
            yield I(r['id'])


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

# Relations the canonical DDL creates, read off the DDL itself so there is no second list to
# keep in sync. Checked with `to_regclass`, which resolves through the connection's search_path.
_DDL_OBJECT = re.compile(r'^CREATE (?:UNIQUE )?(?:TABLE|INDEX) IF NOT EXISTS (\w+)')
_SQL_EXAMPLE_HINT = ('Provision it once as a role that can (e.g. the schema owner, or with '
                     'sql/examples/postgres-schema.sql from the onya repository), then reconnect.')


def _core_objects() -> list[str]:
    return [m.group(1) for stmt in ddl_statements(POSTGRES) if (m := _DDL_OBJECT.match(stmt))]


def _is_privilege_error(e: Exception) -> bool:
    return getattr(e, 'sqlstate', None) == '42501'  # insufficient_privilege (incl. "must be owner")


async def _missing_relations(conn, names: list[str]) -> list[str]:
    rows = await conn.fetch('SELECT n FROM unnest($1::text[]) AS n WHERE to_regclass(n) IS NULL', names)
    return [r['n'] for r in rows]


async def _try_ddl(conn, *stmts: str) -> Exception | None:
    '''Run DDL in a savepoint (a failure must not abort the bootstrap); return the error, if any.'''
    try:
        async with conn.transaction():
            for stmt in stmts:
                await conn.execute(stmt)
    except Exception as e:  # asyncpg.PostgresError; asyncpg itself is imported lazily
        return e
    return None


async def _ensure_schema(conn) -> None:
    '''
    Create the schema only if something is missing. PostgreSQL checks CREATE privilege even for
    `CREATE ... IF NOT EXISTS` on an existing object, so running the DDL unconditionally would
    lock out an application role that only has data privileges on a schema someone else
    provisioned. When DDL is needed but not permitted, fail with the objects that are missing.
    '''
    missing = await _missing_relations(conn, _core_objects())
    if missing:
        err = await _try_ddl(conn, *ddl_statements(POSTGRES))
        if err is not None:
            if _is_privilege_error(err):
                raise StoreError(
                    f'The onya store schema is incomplete (missing: {", ".join(missing)}) and the '
                    f'connecting role may not create it ({err}). {_SQL_EXAMPLE_HINT}'
                ) from err
            raise err
    for key, expected in (('schema_version', SCHEMA_VERSION),
                          ('skeleton_hash_version', SKELETON_HASH_VERSION)):
        val = await conn.fetchval('SELECT value FROM onya_meta WHERE key = $1', key)
        if val is None:
            await conn.execute('INSERT INTO onya_meta (key, value) VALUES ($1, $2)', key, expected)
        elif val != expected:
            raise UnknownSchemaVersion(found=val, expected=expected)


# Mirror of `onya.query.normalize` in SQL: lowercase, collapse non-alphanumeric runs to one
# space, trim. IMMUTABLE so it can back an expression index. (`lower` rather than Python's
# `casefold`: they differ only for a few characters such as `ß`.)
_NORMALIZE_FN = '''
    CREATE OR REPLACE FUNCTION onya_normalize(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT btrim(regexp_replace(lower(t), '[^[:alnum:]]+', ' ', 'g')) $$
'''


async def _ensure_search(conn) -> bool:
    '''
    Bootstrap search support, creating only what's missing: the ``onya_normalize`` function,
    the ``pg_trgm`` extension (stock PostgreSQL and the usual hosted offerings ship it), and a
    GIN trigram index over normalized property values. Returns whether indexed-path search is
    usable (extension + function). Search is optional, so nothing here fails the open: each
    step runs in a savepoint, and a role that can't create a missing object just gets a logged
    notice and, at worst, in-process ranking.

    An existing ``onya_normalize`` is left as is (not ``CREATE OR REPLACE``d, which would need
    ownership); if its definition ever changes, this must compare definitions before skipping.
    '''
    async def has_fn() -> bool:
        return bool(await conn.fetchval("SELECT to_regprocedure('onya_normalize(text)') IS NOT NULL"))

    async def has_ext() -> bool:
        return bool(await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))

    if not await has_fn() and (err := await _try_ddl(conn, _NORMALIZE_FN)) is not None:
        logger.info('onya_normalize() could not be created (%s); onya search will rank in-process', err)
    if not await has_ext() and (err := await _try_ddl(conn, 'CREATE EXTENSION IF NOT EXISTS pg_trgm')) is not None:
        logger.info('pg_trgm could not be enabled (%s); onya search will rank in-process', err)
    usable = await has_ext() and await has_fn()
    if not usable:
        logger.info('pg_trgm unavailable; onya search will rank in-process (unindexed)')
        return False
    if await _missing_relations(conn, ['onya_assertion_value_trgm']):
        err = await _try_ddl(conn, 'CREATE INDEX IF NOT EXISTS onya_assertion_value_trgm ON onya_assertion'
                                   " USING gin (onya_normalize(value) gin_trgm_ops) WHERE kind = 'P'")
        if err is not None:
            logger.info('onya search trigram index could not be created (%s); trigram search runs unindexed', err)
    return True


def _search_filters(args: list, labels, types) -> str:
    '''SQL fragment for the SearchStore label/interp and type filters, appending to ``args``.'''
    sql = ''
    if labels is not None:
        args.append(labels)
        sql += f' AND a.label = ANY(${len(args)}::text[])'
    else:
        args.append(str(rel.TEXT_INTERP))
        sql += f' AND (a.interp IS NULL OR a.interp = ${len(args)})'
    if types is not None:
        args.append(types)
        sql += (' AND EXISTS (SELECT 1 FROM onya_node_type nt WHERE nt.node_pk = a.origin_node'
                f' AND nt.type_iri = ANY(${len(args)}::text[]))')
    return sql


async def _search_candidates(conn, gpk: int, labels, types) -> list:
    '''Unindexed fallback: every first-level property row the search should score.'''
    args: list = [gpk]
    sql = (
        'SELECT i.id AS node_id, a.label, a.value FROM onya_assertion a'
        ' JOIN onya_node n ON n.node_pk = a.origin_node'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk'
        " WHERE a.graph_pk = $1 AND a.kind = 'P'"
    ) + _search_filters(args, labels, types)
    return await conn.fetch(sql, *args)


async def _search_trgm(conn, gpk: int, query: str, labels, types, min_score: float) -> list:
    '''Indexed search (call inside a transaction: the trigram thresholds are ``SET LOCAL``).'''
    q = await conn.fetchval('SELECT onya_normalize($1)', query)  # same normalization as the index
    if not q:
        return []
    for knob in ('pg_trgm.similarity_threshold', 'pg_trgm.word_similarity_threshold'):
        await conn.execute('SELECT set_config($1, $2, true)', knob, str(min_score))
    # $2 query; $3 contains-pattern (index-served; also covers exact/prefix/word); $4 prefix
    # pattern; $5 whole-word pattern. A normalized query holds only alphanumerics and spaces,
    # so it needs no LIKE escaping.
    args: list = [gpk, q, f'%{q}%', f'{q} %', f'% {q} %']
    filters = _search_filters(args, labels, types)
    sql = f'''
        WITH c AS (
            SELECT i.id AS node_id, a.label, a.value, onya_normalize(a.value) AS nv
            FROM onya_assertion a
            JOIN onya_node n ON n.node_pk = a.origin_node
            JOIN onya_ident i ON i.ident_pk = n.ident_pk
            WHERE a.graph_pk = $1 AND a.kind = 'P'{filters}
              AND (onya_normalize(a.value) LIKE $3
                   OR $2 % onya_normalize(a.value)
                   OR $2 <% onya_normalize(a.value))
        ), t AS (
            SELECT node_id, label, value, nv,
                   CASE WHEN nv = $2 THEN 'exact'
                        WHEN nv LIKE $4 THEN 'prefix'
                        WHEN (' ' || nv || ' ') LIKE $5 THEN 'word'
                        ELSE 'fuzzy' END AS tier
            FROM c
        )
        SELECT node_id, label, value, tier,
               CASE tier WHEN 'exact' THEN 1.0
                         WHEN 'fuzzy' THEN greatest(similarity($2, nv), word_similarity($2, nv))
                         ELSE similarity($2, nv) END AS score
        FROM t
    '''
    return await conn.fetch(sql, *args)


async def _ensure_pgq(conn) -> bool:
    '''
    Returns whether both property graphs exist afterwards. They're left as is when present
    (refreshing needs ownership); when missing and not creatable, the store opens without the
    ``GraphQueryStore`` capability instead of failing. (Unverified against PostgreSQL 19 here.)
    '''
    if not await _missing_relations(conn, ['onya_base', 'onya_reified']):
        return True
    err = await _try_ddl_pgq(conn)
    if err is not None:
        if not _is_privilege_error(err):
            raise err
        logger.info('SQL/PGQ property graphs could not be created (%s); GraphQueryStore unavailable', err)
        return False
    return True


async def _try_ddl_pgq(conn) -> Exception | None:
    try:
        async with conn.transaction():
            await _create_pgq(conn)
    except Exception as e:  # asyncpg.PostgresError
        return e
    return None


async def _create_pgq(conn) -> None:
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


async def _nested_prop_values(conn, apk: int, label: str) -> list:
    '''
    Every property value at ANY nesting depth under ``apk`` sharing ``label`` -- what
    ``where=`` actually needs to search (see ``rel.where_matches_values``): `@confidence`
    nests under `@method`, itself nested under the matched assertion, so a direct-children
    search would silently never find it. One recursive-CTE round trip per candidate row.
    '''
    rows = await conn.fetch(
        '''
        WITH RECURSIVE descendants(apk) AS (
            SELECT assertion_pk FROM onya_assertion WHERE origin_assertion = $1
            UNION ALL
            SELECT a.assertion_pk FROM onya_assertion a
            JOIN descendants d ON a.origin_assertion = d.apk
        )
        SELECT value FROM onya_assertion
        WHERE assertion_pk IN (SELECT apk FROM descendants) AND label = $2 AND kind = 'P'
        ''',
        apk, label,
    )
    return [r['value'] for r in rows]


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


async def _write_graph(conn, name: str, g, *, merge: bool) -> list:
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

    return await _write_prefixes(conn, gpk, getattr(g, 'prefixes', None))


async def _read_prefixes(conn, gpk: int) -> dict[str, str]:
    rows = await conn.fetch(
        'SELECT prefix, namespace FROM onya_graph_prefix WHERE graph_pk = $1 ORDER BY prefix', gpk)
    return {r['prefix']: r['namespace'] for r in rows}


async def _write_prefixes(conn, gpk: int, prefixes: dict | None) -> list:
    '''
    Fold ``prefixes`` into the stored map (stored binding wins; ``_relational.write_prefixes``
    rule). Insert-if-absent then read back, so concurrent writers converge on one binding and
    the clash report reflects whichever binding actually won.
    '''
    for k, v in sorted((prefixes or {}).items()):
        await conn.execute('INSERT INTO onya_graph_prefix (graph_pk, prefix, namespace)'
                           ' VALUES ($1, $2, $3) ON CONFLICT DO NOTHING', gpk, k, v)
    stored = await _read_prefixes(conn, gpk)
    return [(k, stored[k], v) for k, v in sorted((prefixes or {}).items())
            if namespace_for_curie(stored[k]) != namespace_for_curie(v)]


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
    g = graph(prefixes=await _read_prefixes(conn, gpk))

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


# --- OverlayReadStore: bulk row fetch + shared reduction (onya.store._relational) ---

async def _resolve_graph_pks(conn, names: list[str]) -> list[int]:
    if not names:
        raise ValueError('union()/match_across()/subgraph_across() need at least one name')
    gpks = []
    for name in names:
        gpk = await _graph_pk(conn, name)
        if gpk is None:
            raise KeyError(name)
        gpks.append(gpk)
    return gpks


async def _with_prefixes(conn, g: graph, gpks: list[int]) -> graph:
    '''Attach the named graphs' stored prefixes, folded in `names` order (first wins, warns on a
    clash, as chaining `graph.union()` would).'''
    for gpk in gpks:
        g.add_prefixes(await _read_prefixes(conn, gpk))
    return g


async def _build_union(conn, gpks: list[int]) -> graph:
    ident_rows = await conn.fetch(
        'SELECT ident_pk, id FROM onya_ident WHERE graph_pk = ANY($1::bigint[])', gpks)
    idents = [(r['ident_pk'], r['id']) for r in ident_rows]

    node_rows = await conn.fetch(
        'SELECT n.node_pk, n.ident_pk FROM onya_node n'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = ANY($1::bigint[])', gpks)
    nodes = [(r['node_pk'], r['ident_pk']) for r in node_rows]

    type_rows = await conn.fetch(
        'SELECT nt.node_pk, nt.type_iri FROM onya_node_type nt'
        ' JOIN onya_node n ON n.node_pk = nt.node_pk'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = ANY($1::bigint[])', gpks)
    node_types = [(r['node_pk'], r['type_iri']) for r in type_rows]

    arows = await conn.fetch(
        'SELECT assertion_pk, kind, origin_node, origin_assertion, label, target_ident,'
        ' value, ident_pk, interp FROM onya_assertion WHERE graph_pk = ANY($1::bigint[])'
        ' ORDER BY assertion_pk', gpks)
    assertions = [
        (r['assertion_pk'], r['kind'], r['origin_node'], r['origin_assertion'], r['label'],
         r['target_ident'], r['value'], r['ident_pk'], r['interp'])
        for r in arows
    ]
    return rel.build_union(idents, nodes, node_types, assertions)


async def _fetch_overlay_rows(conn, gpk_to_name: dict[int, str]):
    '''Like ``_build_union``'s row fetch, but the assertion rows carry each row's source
    graph name (``build_overlay`` needs it for `key()`; ``build_union`` never does).'''
    gpks = list(gpk_to_name)
    ident_rows = await conn.fetch(
        'SELECT ident_pk, id FROM onya_ident WHERE graph_pk = ANY($1::bigint[])', gpks)
    idents = [(r['ident_pk'], r['id']) for r in ident_rows]

    node_rows = await conn.fetch(
        'SELECT n.node_pk, n.ident_pk FROM onya_node n'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = ANY($1::bigint[])', gpks)
    nodes = [(r['node_pk'], r['ident_pk']) for r in node_rows]

    type_rows = await conn.fetch(
        'SELECT nt.node_pk, nt.type_iri FROM onya_node_type nt'
        ' JOIN onya_node n ON n.node_pk = nt.node_pk'
        ' JOIN onya_ident i ON i.ident_pk = n.ident_pk WHERE i.graph_pk = ANY($1::bigint[])', gpks)
    node_types = [(r['node_pk'], r['type_iri']) for r in type_rows]

    arows = await conn.fetch(
        'SELECT assertion_pk, graph_pk, kind, origin_node, origin_assertion, label, target_ident,'
        ' value, ident_pk, interp FROM onya_assertion WHERE graph_pk = ANY($1::bigint[])'
        ' ORDER BY assertion_pk', gpks)
    assertions = [
        (r['assertion_pk'], gpk_to_name[r['graph_pk']], r['kind'], r['origin_node'], r['origin_assertion'],
         r['label'], r['target_ident'], r['value'], r['ident_pk'], r['interp'])
        for r in arows
    ]
    return idents, nodes, node_types, assertions


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
