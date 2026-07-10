# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store._relational
'''
Shared relational core for the SQL store backends.

Everything that must be identical between SQLite and PostgreSQL lives here exactly once:

- the canonical DDL, parameterized by dialect (identity columns, ``BYTEA``/``BLOB``);
- **skeleton hash v1** — structural identity of an assertion made a value (see
  doc/design-persistence-architecture.md § The skeleton hash);
- ``classify_anonymous`` — the pure interp-amendment decision (equal merges / one-sided
  adopts / conflicting stays distinct / NULL-adopts-nothing under ambiguity);
- ``write_graph`` — the write-path merge algorithm over a DB-API cursor, and the
  ``onya_edge_hop`` companion-table maintenance that goes with it.

The write path is written against a synchronous DB-API cursor (``execute`` with ``?``
placeholders, ``fetchone``/``fetchall``, ``lastrowid``). SQLite drives it directly inside a
worker thread; PostgreSQL mirrors its structure asynchronously in ``onya.store.postgres``,
reusing ``skeleton_hash``, ``classify_anonymous``, and the DDL so the *semantics* are shared
even though the I/O plumbing differs. SQLite is thus the proving ground that the projection
carries no Postgres-isms.

Note on a design-doc discrepancy (flagged per the ticket): the pseudocode in
design-persistence-architecture.md § Merge on write treats "incoming interp is NULL and a
row exists" as an unconditional merge. That predates the ratified **NULL-adopts** ruling in
design-interpretations-literate.md § Merge semantics, which ``onya.graph`` implements: a
contract-free incoming assertion whose skeleton is already represented by *two or more
differing contracts* adopts neither and is dropped. Because "merge semantics are the write
semantics", ``classify_anonymous`` follows the model (the ruling), not the older pseudocode.

Second discrepancy: the architecture doc's ``onya_assertion_skeleton`` unique index omits a
predicate. It must be *partial* over anonymous rows only (``WHERE ident_pk IS NULL``), else an
identified assertion and an anonymous one sharing a skeleton and interp collide — which Rule 3
explicitly permits. Corrected in ``ddl_statements``.
'''

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from onya.graph import GraphMergeError, edge

SKELETON_HASH_VERSION = '1'
SCHEMA_VERSION = '1'

_SEP = b'\x1f'  # field separator; cannot occur in an IRI


# --- dialects -----------------------------------------------------------------------

@dataclass(frozen=True)
class Dialect:
    '''The handful of SQL spellings that differ between the two SQL backends.'''
    name: str
    identity_pk: str   # column definition for an auto-assigned BIGINT primary key
    blob_type: str     # binary column type for skeleton_hash


SQLITE = Dialect(
    name='sqlite',
    identity_pk='INTEGER PRIMARY KEY',       # rowid alias; auto-increments
    blob_type='BLOB',
)

POSTGRES = Dialect(
    name='postgres',
    identity_pk='BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY',
    blob_type='BYTEA',
)


def ddl_statements(d: Dialect) -> list[str]:
    '''The canonical schema as a list of ``CREATE`` statements for dialect ``d``.'''
    pk = d.identity_pk
    blob = d.blob_type
    return [
        'CREATE TABLE IF NOT EXISTS onya_meta ('
        ' key TEXT PRIMARY KEY,'
        ' value TEXT NOT NULL)',

        'CREATE TABLE IF NOT EXISTS onya_graph ('
        f' graph_pk {pk},'
        ' name TEXT NOT NULL UNIQUE)',

        'CREATE TABLE IF NOT EXISTS onya_ident ('
        f' ident_pk {pk},'
        ' graph_pk BIGINT NOT NULL REFERENCES onya_graph(graph_pk) ON DELETE CASCADE,'
        ' id TEXT NOT NULL,'
        ' UNIQUE (graph_pk, id))',

        'CREATE TABLE IF NOT EXISTS onya_node ('
        f' node_pk {pk},'
        ' ident_pk BIGINT NOT NULL UNIQUE REFERENCES onya_ident(ident_pk) ON DELETE CASCADE)',

        'CREATE TABLE IF NOT EXISTS onya_node_type ('
        ' node_pk BIGINT NOT NULL REFERENCES onya_node(node_pk) ON DELETE CASCADE,'
        ' type_iri TEXT NOT NULL,'
        ' PRIMARY KEY (node_pk, type_iri))',

        'CREATE TABLE IF NOT EXISTS onya_assertion ('
        f' assertion_pk {pk},'
        ' graph_pk BIGINT NOT NULL REFERENCES onya_graph(graph_pk) ON DELETE CASCADE,'
        " kind CHAR(1) NOT NULL CHECK (kind IN ('E','P')),"
        ' origin_node BIGINT REFERENCES onya_node(node_pk) ON DELETE CASCADE,'
        ' origin_assertion BIGINT REFERENCES onya_assertion(assertion_pk) ON DELETE CASCADE,'
        ' label TEXT NOT NULL,'
        ' target_ident BIGINT REFERENCES onya_ident(ident_pk),'
        ' value TEXT,'
        ' ident_pk BIGINT UNIQUE REFERENCES onya_ident(ident_pk),'
        ' interp TEXT,'
        f' skeleton_hash {blob} NOT NULL,'
        ' CHECK ((origin_node IS NULL) <> (origin_assertion IS NULL)),'
        " CHECK ((kind = 'E' AND target_ident IS NOT NULL AND value IS NULL)"
        "     OR (kind = 'P' AND value IS NOT NULL AND target_ident IS NULL)))",

        'CREATE TABLE IF NOT EXISTS onya_edge_hop ('
        ' assertion_pk BIGINT PRIMARY KEY REFERENCES onya_assertion(assertion_pk) ON DELETE CASCADE,'
        ' source_ident BIGINT NOT NULL REFERENCES onya_ident(ident_pk),'
        ' target_ident BIGINT NOT NULL REFERENCES onya_ident(ident_pk),'
        ' label TEXT NOT NULL)',

        'CREATE INDEX IF NOT EXISTS onya_assertion_origin_node'
        ' ON onya_assertion (graph_pk, origin_node, label)',
        'CREATE INDEX IF NOT EXISTS onya_assertion_origin_assertion'
        ' ON onya_assertion (graph_pk, origin_assertion, label)',
        'CREATE INDEX IF NOT EXISTS onya_assertion_target'
        ' ON onya_assertion (graph_pk, target_ident)',
        # Partial (anonymous-only) unique index. Rule 3 lets an identified assertion coexist
        # with an anonymous one of the same skeleton and interp, so the uniqueness backstop
        # must exclude identified rows — otherwise the two collide. (The architecture doc's
        # DDL omits this predicate; corrected here. See module docstring.)
        'CREATE UNIQUE INDEX IF NOT EXISTS onya_assertion_skeleton'
        " ON onya_assertion (graph_pk, skeleton_hash, COALESCE(interp, ''))"
        ' WHERE ident_pk IS NULL',
        'CREATE INDEX IF NOT EXISTS onya_edge_hop_source ON onya_edge_hop (source_ident, label)',
    ]


# --- skeleton hash v1 ---------------------------------------------------------------

def skeleton_hash(kind: str, origin_key: str, label: str, target_or_value: str) -> bytes:
    '''
    SHA-256 over the canonical byte string (v1):

        edge:      "E" 0x1F origin_key 0x1F label 0x1F target_id
        property:  "P" 0x1F origin_key 0x1F label 0x1F value

    computed on model values (post-``@iri``-expansion IRIs), never on serialized forms.
    ``origin_key`` is the origin node's id (top-level), the parent assertion's explicit id
    (nested under an identified assertion), or ``hex(parent skeleton_hash)`` (nested under an
    anonymous one).
    '''
    h = hashlib.sha256()
    h.update(kind.encode('utf-8'))
    for part in (origin_key, label, target_or_value):
        h.update(_SEP)
        h.update(part.encode('utf-8'))
    return h.digest()


def hexhash(digest: bytes) -> str:
    return digest.hex()


# --- assertion traversal ------------------------------------------------------------

@dataclass
class ARecord:
    '''One assertion flattened for the write path, in pre-order (parent before child).'''
    obj: object            # the model assertion, used only as an identity key for parent lookup
    parent: object | None  # the parent assertion, or None for a node-origin assertion
    kind: str              # 'E' | 'P'
    label: str
    target_id: str | None  # kind == 'E'
    value: str | None      # kind == 'P'
    interp: str | None
    explicit_id: str | None
    skeleton: bytes


def iter_records(node) -> list[ARecord]:
    '''Flatten a node's assertions (recursively) into pre-order ``ARecord``s with hashes.'''
    records: list[ARecord] = []

    def walk(container, parent, origin_key: str):
        for a in list(container.properties) + list(container.edges):
            is_edge = isinstance(a, edge)
            kind = 'E' if is_edge else 'P'
            label = str(a.label)
            if is_edge:
                target_id = str(a.target.id)
                value = None
                payload = target_id
            else:
                target_id = None
                value = str(a.value)
                payload = value
            sk = skeleton_hash(kind, origin_key, label, payload)
            eid = str(a.id) if a.id is not None else None
            interp = str(a.interp) if a.interp is not None else None
            records.append(ARecord(a, parent, kind, label, target_id, value, interp, eid, sk))
            child_key = eid if eid is not None else hexhash(sk)
            walk(a, a, child_key)

    walk(node, None, str(node.id))
    return records


# --- interp-amendment decision (pure) -----------------------------------------------

def classify_anonymous(existing: list[tuple[int, str | None]], incoming_interp: str | None):
    '''
    Decide what to do with an incoming anonymous assertion given the existing rows sharing
    its skeleton (each ``(assertion_pk, interp)``; the unique index guarantees at most one
    row per distinct interp, including at most one NULL row). Returns ``(action, pk,
    set_interp)``:

    - ``('merge', pk, None)``       — fold into the row ``pk`` (interp already compatible);
    - ``('merge', pk, X)``          — fold into NULL row ``pk`` and UPDATE its interp to X
                                       (one-sided adoption);
    - ``('insert', None, None)``    — no compatible row; insert a new one;
    - ``('drop', None, None)``      — contract-free incoming, skeleton already represented by
                                       >= 2 differing contracts: adopts nothing, adds nothing.
    '''
    by_interp = {i: pk for pk, i in existing}
    if incoming_interp is not None:
        if incoming_interp in by_interp:
            return ('merge', by_interp[incoming_interp], None)
        if None in by_interp:                                   # adopt: NULL row takes the contract
            return ('merge', by_interp[None], incoming_interp)
        return ('insert', None, None)
    # incoming is contract-free
    if None in by_interp:
        return ('merge', by_interp[None], None)
    contracts = [i for i in by_interp if i is not None]
    if len(contracts) == 1:                                     # one-sided adoption of the sole contract
        return ('merge', by_interp[contracts[0]], None)
    if len(contracts) >= 2:                                     # ambiguous: NULL-adopts-nothing
        return ('drop', None, None)
    return ('insert', None, None)


# --- schema lifecycle ---------------------------------------------------------------

def ensure_schema(cur, dialect: Dialect) -> None:
    '''Create the schema if absent and record/verify the version keys. Raises
    ``UnknownSchemaVersion`` if an existing store was built by a different algorithm.'''
    from onya.store.exceptions import UnknownSchemaVersion
    for stmt in ddl_statements(dialect):
        cur.execute(stmt)
    for key, expected in (('schema_version', SCHEMA_VERSION),
                          ('skeleton_hash_version', SKELETON_HASH_VERSION)):
        cur.execute('SELECT value FROM onya_meta WHERE key = ?', (key,))
        row = cur.fetchone()
        if row is None:
            cur.execute('INSERT INTO onya_meta (key, value) VALUES (?, ?)', (key, expected))
        elif row[0] != expected:
            raise UnknownSchemaVersion(found=row[0], expected=expected)


# --- write path (synchronous, DB-API cursor) ----------------------------------------

def _get_or_create_graph(cur, name: str) -> int:
    cur.execute('SELECT graph_pk FROM onya_graph WHERE name = ?', (name,))
    row = cur.fetchone()
    if row is not None:
        return row[0]
    cur.execute('INSERT INTO onya_graph (name) VALUES (?)', (name,))
    return cur.lastrowid


def _get_or_create_ident(cur, graph_pk: int, idv: str) -> int:
    cur.execute('SELECT ident_pk FROM onya_ident WHERE graph_pk = ? AND id = ?', (graph_pk, idv))
    row = cur.fetchone()
    if row is not None:
        return row[0]
    cur.execute('INSERT INTO onya_ident (graph_pk, id) VALUES (?, ?)', (graph_pk, idv))
    return cur.lastrowid


def _get_or_create_node(cur, ident_pk: int) -> int:
    cur.execute('SELECT node_pk FROM onya_node WHERE ident_pk = ?', (ident_pk,))
    row = cur.fetchone()
    if row is not None:
        return row[0]
    cur.execute('INSERT INTO onya_node (ident_pk) VALUES (?)', (ident_pk,))
    return cur.lastrowid


def _insert_assertion(cur, graph_pk, rec: ARecord, origin_node, origin_assertion,
                      target_ident, ident_pk) -> int:
    cur.execute(
        'INSERT INTO onya_assertion'
        ' (graph_pk, kind, origin_node, origin_assertion, label, target_ident, value,'
        '  ident_pk, interp, skeleton_hash)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (graph_pk, rec.kind, origin_node, origin_assertion, rec.label, target_ident,
         rec.value, ident_pk, rec.interp, rec.skeleton),
    )
    return cur.lastrowid


def _maybe_edge_hop(cur, assertion_pk, rec: ARecord, source_ident, target_ident) -> None:
    '''Maintain the base-graph companion table for a top-level (node-origin) edge.'''
    if rec.kind != 'E' or source_ident is None:
        return
    cur.execute(
        'INSERT INTO onya_edge_hop (assertion_pk, source_ident, target_ident, label)'
        ' VALUES (?, ?, ?, ?)',
        (assertion_pk, source_ident, target_ident, rec.label),
    )


def write_graph(cur, name: str, g, *, merge: bool, dialect: Dialect = SQLITE) -> None:
    '''
    Persist ``g`` under ``name`` via the write-path merge algorithm. ``merge=True`` unions
    with the stored graph; ``merge=False`` replaces it wholesale (the relational projection
    is always normalized, so incoming duplicate occurrences collapse either way). The caller
    is responsible for the surrounding transaction and for ``g.validate_id_space()``.
    '''
    name = str(name)
    if not merge:
        cur.execute('DELETE FROM onya_graph WHERE name = ?', (name,))  # ON DELETE CASCADE
    graph_pk = _get_or_create_graph(cur, name)

    ident_cache: dict[str, int] = {}

    def ensure_ident(idv: str) -> int:
        idv = str(idv)
        pk = ident_cache.get(idv)
        if pk is None:
            pk = _get_or_create_ident(cur, graph_pk, idv)
            ident_cache[idv] = pk
        return pk

    # Stratum 0: node idents, node rows, node types.
    node_ident: dict[str, int] = {}
    node_pk_by_id: dict[str, int] = {}
    for nid, n in g.nodes.items():
        ipk = ensure_ident(nid)
        node_ident[str(nid)] = ipk
        npk = _get_or_create_node(cur, ipk)
        node_pk_by_id[str(nid)] = npk
        for t in sorted(n.types, key=str):
            # Idempotent on re-put; a guarded insert keeps the DDL the only dialect divergence.
            cur.execute('SELECT 1 FROM onya_node_type WHERE node_pk = ? AND type_iri = ?', (npk, str(t)))
            if cur.fetchone() is None:
                cur.execute('INSERT INTO onya_node_type (node_pk, type_iri) VALUES (?, ?)', (npk, str(t)))

    # Strata 1..n: assertions, pre-order per node so a parent row exists before its children.
    for nid, n in g.nodes.items():
        src_ident = node_ident[str(nid)]
        pk_by_obj: dict[int, int] = {}
        for rec in iter_records(n):
            if rec.parent is None:
                origin_node, origin_assertion = node_pk_by_id[str(nid)], None
                edge_source = src_ident
            else:
                parent_pk = pk_by_obj.get(id(rec.parent))
                if parent_pk is None:      # parent was dropped (NULL-adopts) — skip its subtree
                    continue
                origin_node, origin_assertion = None, parent_pk
                edge_source = None         # nested edges are reified-graph structure, not base hops
            target_ident = ensure_ident(rec.target_id) if rec.kind == 'E' else None

            if rec.explicit_id is not None:
                apk = _put_identified(cur, graph_pk, rec, origin_node, origin_assertion,
                                      target_ident, ensure_ident, edge_source)
            else:
                apk = _put_anonymous(cur, graph_pk, rec, origin_node, origin_assertion,
                                     target_ident, edge_source)
            if apk is not None:
                pk_by_obj[id(rec.obj)] = apk


def _put_identified(cur, graph_pk, rec, origin_node, origin_assertion, target_ident,
                    ensure_ident, edge_source):
    '''Rule 1: an identified assertion matches on its ident; skeleton and interp must agree.'''
    aipk = ensure_ident(rec.explicit_id)
    cur.execute(
        'SELECT assertion_pk, skeleton_hash, interp FROM onya_assertion'
        ' WHERE graph_pk = ? AND ident_pk = ?',
        (graph_pk, aipk),
    )
    row = cur.fetchone()
    if row is not None:
        apk, sk_db, interp_db = row[0], bytes(row[1]), row[2]
        if sk_db != rec.skeleton:
            raise GraphMergeError(
                f'Assertion id {rec.explicit_id!r} has a stored skeleton differing from the '
                f'incoming one (Rule 1: same id implies same skeleton).'
            )
        if interp_db is not None and rec.interp is not None and interp_db != rec.interp:
            raise GraphMergeError(
                f'Assertion id {rec.explicit_id!r} carries a differing interpretation: '
                f'{interp_db!r} vs {rec.interp!r}.'
            )
        if interp_db is None and rec.interp is not None:
            cur.execute('UPDATE onya_assertion SET interp = ? WHERE assertion_pk = ?',
                        (rec.interp, apk))
        return apk
    apk = _insert_assertion(cur, graph_pk, rec, origin_node, origin_assertion, target_ident, aipk)
    _maybe_edge_hop(cur, apk, rec, edge_source, target_ident)
    return apk


def _put_anonymous(cur, graph_pk, rec, origin_node, origin_assertion, target_ident, edge_source):
    '''Rule 2 + interp amendment: match anonymous rows by skeleton, decide via classify.'''
    cur.execute(
        'SELECT assertion_pk, interp FROM onya_assertion'
        ' WHERE graph_pk = ? AND skeleton_hash = ? AND ident_pk IS NULL',
        (graph_pk, rec.skeleton),
    )
    existing = [(r[0], r[1]) for r in cur.fetchall()]
    action, pk, set_interp = classify_anonymous(existing, rec.interp)
    if action == 'drop':
        return None
    if action == 'merge':
        if set_interp is not None:
            cur.execute('UPDATE onya_assertion SET interp = ? WHERE assertion_pk = ?',
                        (set_interp, pk))
        return pk
    apk = _insert_assertion(cur, graph_pk, rec, origin_node, origin_assertion, target_ident, None)
    _maybe_edge_hop(cur, apk, rec, edge_source, target_ident)
    return apk
