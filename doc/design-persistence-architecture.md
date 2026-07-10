**Design: Pluggable persistence layer for the Onya Python library**

Status: draft for review, pre-implementation. Assumes
[SPEC.md](../SPEC.md) (especially § Assertion Identifiers and § Identity
and graph merge) and the interpretation design trio, particularly
[design-interpretations-pylib.md](design-interpretations-pylib.md) and the
merge amendment in
[design-interpretations-literate.md](design-interpretations-literate.md).
The merge rules are load-bearing throughout this document: a persistence
backend is correct exactly when a round trip through it is
indistinguishable from an in-memory graph union.

## Motivation

The Onya library today parses, builds, and serializes graphs entirely in
memory. That is the right center of gravity — the model is small and the
Literate format is the interchange story — but real use accumulates graphs
across sessions, processes, and pipelines. We need durable storage that:

- keeps the core model untouched and unaware of storage;
- starts with something trivially inspectable (files on disk) that doubles
  as the test fake;
- scales through SQLite (single-file, zero-configuration, zero added
  dependencies) to PostgreSQL (concurrent, networked, production);
- is positioned for PostgreSQL 19's native SQL/PGQ property graph queries
  without betting the design on them.

One fact discovered during research shapes the whole PostgreSQL story:
SQL/PGQ in PG 19 defines property graphs as *definitions over existing
relational tables* — a view-like schema object, no new storage engine, no
extension, no data migration. That means we do not build a "PG 17 backend"
and a separate "PG 19 backend." We build **one relational projection of
the Onya model**, served by one asyncpg driver, and the PG 19 support is a
`CREATE PROPERTY GRAPH` definition plus a query surface layered on the
same tables. The eventual deprecation of PG 17 support then deletes
nothing but a version check.

## Ground rules

- **Storage is a peripheral, not an organ.** Nothing in `onya/graph.py`,
  the parser, or the interp layer imports the store. The store imports the
  core, only. This is also the extraction seam: the whole subpackage can
  move to a supplementary distribution later (see § Packaging) as a file
  move, not a refactor.
- **The string layer round-trips absolutely.** What goes in comes out:
  property values byte-identical, `interp` and explicit `id` preserved,
  unknown interpretation IRIs untouched. No backend ever "helpfully"
  types, trims, or normalizes a value. Typed storage is a *projection*
  concern (§ Analytics projection), always derived, never primary.
- **Merge semantics are the write semantics.** Writing a graph into a
  store that already holds one is a graph union under SPEC merge Rules
  1–3 plus the interp compatibility amendment. A backend that cannot
  honor those rules cannot claim the merge capability.
- **Async-first, sync-tolerant.** The protocol is `async`; asyncpg
  demands it and modern callers expect it. Backends with no async I/O
  underneath (files, stdlib `sqlite3`) implement the same protocol,
  delegating to `asyncio.to_thread` where a call might block. A thin
  `onya.store.sync` wrapper (essentially `asyncio.run` per call) serves
  scripts and REPL use; it is a convenience, not a second protocol.
- **Capabilities over inheritance.** Backends differ in power. Rather
  than one fat interface with `NotImplementedError` landmines, we define
  a minimal base protocol plus optional capability protocols, discovered
  by `isinstance` (all are `runtime_checkable` Protocols).

## The store abstraction

### Base protocol: `GraphStore`

The floor every backend must meet: named whole graphs, checkpoint-style.

```python
# onya/store/base.py
from typing import Protocol, runtime_checkable
from collections.abc import AsyncIterator
from amara.iri import I
from onya.graph import graph

@runtime_checkable
class GraphStore(Protocol):
    async def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        '''Persist g under name. merge=True (default) unions with any stored
        graph per SPEC merge rules; merge=False replaces wholesale.'''

    async def get(self, name: I | str) -> graph:
        '''Load the named graph, fully materialized. KeyError if absent.'''

    async def drop(self, name: I | str) -> None: ...

    def names(self) -> AsyncIterator[I | str]: ...

    async def __aenter__(self) -> 'GraphStore': ...
    async def __aexit__(self, *exc) -> None: ...
```

Graph names are IRIs, naturally aligning with `@document` in the
docheader: the common case is that a stored graph's name is its document
IRI. A store holds many named graphs; one Postgres database or SQLite
file can serve a whole application.

### Capability: `AssertionStore`

Fine-grained access without materializing the whole graph. The query
shape deliberately mirrors `graph.match()` — the existing tuple contract
`(origin, relation, target, annotations)` — so code written against the
in-memory API ports by adding `await`/`async for`.

```python
@runtime_checkable
class AssertionStore(Protocol):
    def match(self, name: I | str, origin: I | str | None = None,
              label: I | str | None = None,
              ) -> AsyncIterator[tuple[I | str, I | str, str | I, dict]]:
        '''Stream assertions matching the given constraints, without
        loading the graph. None means unconstrained.'''

    async def subgraph(self, name: I | str, roots: set[I | str],
                       hops: int = 1) -> graph:
        '''Materialize only the neighborhood of the given node ids —
        the working-set loader for graphs too big to get() whole.'''

    async def add(self, name, origin, label, target_or_value, *,
                  kind, interp=None, id_=None) -> None: ...
    async def remove(self, name, origin, label, target_or_value, *, kind) -> None: ...
```

File backend: not offered (it would be a lie — the file must be parsed
whole anyway). SQLite and Postgres: offered.

### Capability: `GraphQueryStore` (PG 19)

```python
@runtime_checkable
class GraphQueryStore(Protocol):
    async def graph_table(self, sql: str, *args) -> list[tuple]:
        '''Execute a query containing GRAPH_TABLE(...) against this
        store's property graph definitions. Escape hatch by design:
        Onya does not wrap PGQ in its own query language.'''
```

Deliberately thin. Onya's stance (see SPEC § Design Principles) is
traversal-first at the model layer and *projection into relational space*
for anything aggregate-shaped — not the invention of a query language.
PGQ **is** relational projection with graph pattern syntax, so the right
API is to hand the user SQL, plus the curated schema documentation in
§ SQL/PGQ layer below.

### Construction

URL-dispatched factory, with backend registration via the
`onya.store.backends` entry-point group so supplementary distributions
can plug in without touching this repo:

```python
from onya.store import connect

async with await connect('file:/var/data/graphs') as store: ...
async with await connect('sqlite:app.db') as store: ...
async with await connect('postgresql://u:p@host/db') as store: ...
```

The Postgres backend probes `server_version` at connect time; on ≥ 19 it
installs/refreshes the property graph definitions and the store instance
additionally satisfies `GraphQueryStore`. No separate URL scheme, no
user-facing PG 17 vs 19 fork.

## Backends

| Backend | Module | Extra deps | GraphStore | AssertionStore | GraphQueryStore |
| --- | --- | --- | --- | --- | --- |
| Literate files | `onya.store.filesystem` | none | ✓ | — | — |
| SQLite | `onya.store.sqlite` | none (stdlib) | ✓ | ✓ | — |
| PostgreSQL ≥ 17 | `onya.store.postgres` | `onya[postgres]` → asyncpg | ✓ | ✓ | — |
| PostgreSQL ≥ 19 | `onya.store.postgres` | `onya[postgres]` | ✓ | ✓ | ✓ |

### Filesystem backend (default; the testing fake)

One Onya Literate file per named graph under a root directory:
`<root>/<slug>.onya` (with `<slug>.onya.md` accepted on read, for those
who want Markdown editor affordances; we emit `.onya`, the repo
convention). The graph name IRI is recorded in the file's own
`@docheader` `@document`, which is authoritative; the slug is a
filesystem-safe digest-suffixed rendering, never parsed back.

`put(merge=True)` is: parse existing file into a graph, union in memory
via the model's merge (the same code path every backend's semantics are
defined against), re-serialize. This backend is therefore
*definitionally correct* — it is the executable specification the SQL
backends are tested against, and the zero-dependency fake for downstream
projects' test suites. Concurrency story: a `.lock` sidecar via
`os.open(O_CREAT|O_EXCL)`; this is a testing and small-tool backend, not
a contended one, and we say so in its docstring.

### SQLite backend

Stdlib `sqlite3` under `asyncio.to_thread` — zero added dependencies, so
it is *not* extras-gated; `pip install onya` includes it. Serialized
writer (SQLite's natural mode), WAL on. Schema and write-path algorithm
are the same as Postgres (below), minus server-specific types: the schema
DDL lives once, in dialect-parameterized form, in
`onya/store/_relational.py`, and both SQL backends consume it. SQLite is
the proving ground that the relational projection has no
Postgres-isms baked into its bones.

## The relational projection (canonical schema)

This is the deferred concern from earlier design discussions, now due:
how Onya's model — recursive assertions, anonymous-by-default identity,
a shared id space for nodes and identified assertions — lands in
relational space without distortion.

### The shared identifier space gets a table

SPEC gives nodes and identified assertions one identifier space
(`AssertionIdConflict` polices it in memory). The relational projection
makes that space first-class:

```sql
CREATE TABLE onya_graph (
    graph_pk   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE            -- the graph's IRI
);

CREATE TABLE onya_ident (
    ident_pk   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    graph_pk   BIGINT NOT NULL REFERENCES onya_graph ON DELETE CASCADE,
    id         TEXT NOT NULL,                  -- IRI (or CURIE-expanded form)
    UNIQUE (graph_pk, id)
);
```

Every node id and every explicit assertion `@id` is a row here. The
`UNIQUE (graph_pk, id)` constraint *is* the shared-space rule: a
collision between a node id and an assertion id is a constraint
violation, surfaced as `AssertionIdConflict`. Edge targets reference
`onya_ident`, which resolves cleanly to *either* a node or an identified
assertion — exactly the late-binding resolution `graph.match()`
documents, with referential integrity thrown in.

```sql
CREATE TABLE onya_node (
    node_pk    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ident_pk   BIGINT NOT NULL UNIQUE REFERENCES onya_ident ON DELETE CASCADE
);

CREATE TABLE onya_node_type (
    node_pk    BIGINT NOT NULL REFERENCES onya_node ON DELETE CASCADE,
    type_iri   TEXT NOT NULL,
    PRIMARY KEY (node_pk, type_iri)
);
```

A node referenced as an edge target but never described (legal in Onya)
is simply an `onya_ident` + bare `onya_node` row — the same shape the
in-memory parser produces.

### Assertions, recursively

```sql
CREATE TABLE onya_assertion (
    assertion_pk     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    graph_pk         BIGINT NOT NULL REFERENCES onya_graph ON DELETE CASCADE,
    kind             CHAR(1) NOT NULL CHECK (kind IN ('E', 'P')),
    -- exactly one origin: a node, or a parent assertion (recursion)
    origin_node      BIGINT REFERENCES onya_node,
    origin_assertion BIGINT REFERENCES onya_assertion,
    label            TEXT NOT NULL,
    target_ident     BIGINT REFERENCES onya_ident,   -- kind = 'E'
    value            TEXT,                           -- kind = 'P'
    ident_pk         BIGINT UNIQUE REFERENCES onya_ident,  -- explicit @id, if any
    interp           TEXT,                           -- interpretation IRI, if any
    skeleton_hash    BYTEA NOT NULL,
    CHECK ((origin_node IS NULL) <> (origin_assertion IS NULL)),
    CHECK ((kind = 'E' AND target_ident IS NOT NULL AND value IS NULL)
        OR (kind = 'P' AND value IS NOT NULL AND target_ident IS NULL))
);

CREATE INDEX ON onya_assertion (graph_pk, origin_node, label);
CREATE INDEX ON onya_assertion (graph_pk, origin_assertion, label);
CREATE INDEX ON onya_assertion (graph_pk, target_ident);   -- reverse traversal
CREATE UNIQUE INDEX onya_assertion_skeleton
    ON onya_assertion (graph_pk, skeleton_hash, COALESCE(interp, ''))
    WHERE ident_pk IS NULL;   -- anonymous rows only; see below
```

The skeleton uniqueness index is **partial** — scoped to anonymous rows
(`ident_pk IS NULL`). Rule 3 lets an identified assertion coexist with an
anonymous one of the same skeleton *and* interp, so an unpartitioned unique
index would wrongly collide the two. Uniqueness is a concurrency backstop for
anonymous merge only; identified assertions are policed by their own
`ident_pk UNIQUE`. (Both PostgreSQL and SQLite support partial indexes.)

Nested assertions are the self-reference `origin_assertion` — the
model's natural recursion, kept as adjacency rather than flattened,
because nesting depth in practice is shallow (annotation-shaped) and
fixed-depth joins cover it; a closure table is an optimization we decline
until measured need.

### The skeleton hash: structural identity, made a column

Anonymous assertions have no stored identifier; their identity *is* the
skeleton `(origin, label, target/value)`, recursively through origins.
In memory, merge compares structures. In SQL, comparing recursive
structures per-write is miserable — so we make the skeleton a value.

`skeleton_hash` is SHA-256 over a canonical UTF-8 byte string, defined
(v1) as:

```
edge:      "E" 0x1F origin_key 0x1F label 0x1F target_id
property:  "P" 0x1F origin_key 0x1F label 0x1F value
origin_key = the origin node's id                  (top-level)
           | the parent assertion's explicit id     (nested under identified)
           | hex(parent's skeleton_hash)            (nested under anonymous)
```

with all IRIs in resolved (post-`@iri`-expansion) form — hashing happens
strictly below the serialization layer, on model values. Field separator
`0x1F` cannot occur in an IRI and property values never embed raw
control characters ambiguously against it after UTF-8 encoding of the
canonical form (values are hashed as-is; only the *separator positions*
matter, and label/origin are IRI-constrained, so the parse of the
canonical string is unambiguous from the left).

Two consequences fall straight out of the SPEC merge rules:

- **Rule 2** (equal anonymous skeletons merge) becomes: same
  `skeleton_hash` ⇒ same assertion. The recursion in "origins compare
  under the merge" is handled because a nested assertion's `origin_key`
  is its parent's identity — explicit id or skeleton hash — so parents
  that merge confer identical origin keys on their children.
- **Rule 1** (same explicit id ⇒ same assertion, skeletons MUST match)
  becomes a comparison of stored vs incoming `skeleton_hash` on the
  `ident_pk` hit; mismatch raises the merge error.
- **Rule 3** (identified never merges with anonymous) is free:
  identified assertions are matched by `ident_pk`, anonymous by
  `skeleton_hash`, and the write path never crosses the streams.

The hash is a **per-store implementation detail**, not (yet) SPEC
material: merges between independent stores happen through the model
layer, which uses real structural comparison. If we ever want wire-level
federation of stores, v1 above gets promoted to a SPEC appendix; until
then it is versioned in-schema (a `onya_meta` key) so it can be evolved
with a rebuild.

### Merge on write: the interp amendment lands in the write path

The interp merge amendment
(design-interpretations-literate.md § Merge semantics) means anonymous
merge is *not* a bare `ON CONFLICT DO NOTHING`. The amendment includes the
ratified **NULL-adopts ruling**: a contract-free (interp-absent) incoming
assertion whose skeleton is already represented by *two or more differing
contracts* can pick no side, so it adopts nothing and adds nothing — it is
dropped. The write path must reproduce the model's group semantics
(`onya.graph`), applied incrementally. Because the partial unique index
guarantees at most one anonymous row per distinct interp (including at most one
NULL row), the case analysis for an incoming anonymous assertion, within one
transaction, is:

```
rows := SELECT ... WHERE graph_pk = $g AND skeleton_hash = $h FOR UPDATE
        (excluding identified rows — Rule 3)

incoming interp is X (non-NULL):
    a row has interp X                        → merge; recurse into children
    else a row has interp NULL                → UPDATE that row SET interp = X   (one-sided adopts)
    else                                      → INSERT new row                   (conflicting stays distinct)

incoming interp is NULL:
    a row has interp NULL                     → merge; recurse into children
    else exactly one contract row present     → merge into it                    (NULL adopts the sole contract)
    else two or more differing contracts      → DROP                             (NULL-adopts-nothing ruling)
    else (no rows)                            → INSERT new NULL row
```

This is order-independent and idempotent, matching the batch group logic in the
model. (An earlier draft of this section treated "incoming interp NULL and a row
exists" as an unconditional merge; that predated the NULL-adopts ruling and is
superseded above — "merge semantics are the write semantics.")

For identified assertions: match on `ident_pk`; skeleton mismatch or
conflicting non-absent interp is a merge error, per Rule 1 and its interp
parallel. The **partial** unique index over `(graph_pk, skeleton_hash,
COALESCE(interp, '')) WHERE ident_pk IS NULL` is the concurrency backstop for
anonymous merge under serialization anomalies, not the mechanism.

Batch shape: the driver loads graphs in topological order (nodes, then
assertions by nesting depth), using `executemany`/`COPY` per stratum;
per-row round trips only where the merge case analysis demands it. On
PG 19, `INSERT ... ON CONFLICT DO SELECT` (new in 19) collapses the
get-or-create round trip for the common no-interp case; the driver uses
it when available, with the portable path as fallback.

## SQL/PGQ layer (PostgreSQL 19)

Because PGQ graphs are definitions over existing tables, the layer is
one migration and one capability, no storage change. Two graph
definitions, because Onya has two useful graph readings:

**The base graph** — domain traversal, nodes and node-to-node edges:

```sql
CREATE PROPERTY GRAPH onya_base
  VERTEX TABLES (
    onya_ident LABEL resource PROPERTIES (id)
  )
  EDGE TABLES (
    onya_edge_hop
      SOURCE KEY (source_ident) REFERENCES onya_ident (ident_pk)
      DESTINATION KEY (target_ident) REFERENCES onya_ident (ident_pk)
      LABEL asserted PROPERTIES (label)
  );
```

**The reified graph** — assertions as vertices, for traversing
annotation structure (provenance chains, interp audits) with the same
pattern syntax.

`onya_edge_hop` above is a thin driver-maintained companion table
(`assertion_pk, source_ident, target_ident, label`), written in the same
transaction as `onya_assertion`. Why not a view over `onya_assertion
WHERE kind = 'E'`? Because whether the initial PG 19 PGQ implementation
accepts views (or predicated subsets of tables) as vertex/edge tables is
**to be verified at implementation time against Beta docs**; the
companion table is the version that certainly works, costs one narrow
index-organized table, and can be dropped for a view if 19 final allows
it. This is the single most important thing to re-check when
implementation starts.

Usage, through the escape-hatch capability:

```python
if isinstance(store, GraphQueryStore):
    rows = await store.graph_table('''
        SELECT * FROM GRAPH_TABLE (onya_base
            MATCH (a IS resource WHERE a.id = $1)
                  -[e IS asserted WHERE e.label = $2]->(b IS resource)
                  -[f IS asserted WHERE f.label = $2]->(c IS resource)
            COLUMNS (c.id AS friend_of_friend))
    ''', str(chuks_iri), str(KNOWS))
```

Known PG 19 limitation, worn openly in our docs: no variable-length or
quantified path patterns in the initial release — fixed-depth hops only;
transitive traversals still mean recursive CTEs over `onya_edge_hop`
(for which the driver ships one canned helper, `reachable(store, name,
root, label, max_hops)`), with quantifiers expected in a later PG
release. This is another reason `GraphQueryStore` stays an escape hatch
rather than the foundation of a Onya query story.

## Analytics projection (user space)

Distinct from the canonical schema above, and the payoff of the
traversal-first stance: aggregate/analytic questions are answered by
*projecting* graph content into ordinary domain tables, then using plain
SQL — not by an aggregate-capable graph query language.

The interpretation layer is the typing bridge, and this is where the
data-contract design earns its keep in persistence. A projection spec
maps a node type to a table, labels to columns, and each column's SQL
type comes from the label's interpretation via the registry — with the
established laws intact (`number` → `NUMERIC`/`BIGINT`, never floats;
`boolean` strict; unknown interps project as `TEXT`, untouched).

```python
from onya.store.project import projection, project

people = projection(
    'people',
    type=SCHEMA_ORG.Person,
    columns={'name': SCHEMA_ORG.name, 'age': SCHEMA_ORG.age},
)  # column types resolved from interp: age asserted @as number → BIGINT/NUMERIC

await project(store, 'http://example.org/friendship-graph', people)
# → CREATE TABLE people AS ... ; ordinary SQL from here on
```

Projection is always *derived and disposable* — regenerate at will;
never a write-back path. Contract checking stays on-demand: `project()`
takes `on_broken_contract='null' | 'skip' | 'error'`, defaulting to
`null` with findings reported as data, in keeping with
`validate()`'s posture. Note for the docs, per the standing caution: our
"data contract layers" language must not lead data-engineering readers
to expect shape-level guarantees here — a projection types *columns from
per-assertion contracts*; it does not impose or verify a schema on the
graph.

This section is architecture-level intent; `project()` gets its own
design pass before implementation.

## Packaging and the extraction seam

- New subpackage `pylib/store/` (→ `onya.store` after the wheel remap),
  containing `base`, `filesystem`, `sqlite`, `_relational`, `postgres`,
  `project`.
- `pyproject.toml` gains:

  ```toml
  [project.optional-dependencies]
  postgres = ["asyncpg>=0.30"]

  [project.entry-points."onya.store.backends"]
  file = "onya.store.filesystem:FileStore"
  sqlite = "onya.store.sqlite:SqliteStore"
  postgresql = "onya.store.postgres:PostgresStore"
  ```

- `onya.store.postgres` imports asyncpg lazily inside `connect()`,
  raising `ImportError('PostgreSQL support requires: pip install
  "onya[postgres]"')`.
- On the standing question of whether relational backends belong in this
  repo at all: they stay, for now, for velocity and shared test
  infrastructure. The ground rules make later extraction mechanical:
  `onya.store.postgres` + `_relational` (+ `project`) move to a
  supplementary distribution, registering through the same entry-point
  group. One caution for that day: a PEP 420 namespace-package split
  (`onya.db` as its own distribution) interacts badly with this repo's
  `pylib → onya` wheel remap (`onya/__init__.py` exists, so `onya` is a
  regular package). A sibling top-level distribution name
  (`onya-db` providing `onya_db`, or re-exporting under a documented
  alias) avoids fighting the packaging tools; decide then, not now.

## Testing strategy

One behavioral conformance suite, parameterized over every backend —
the store-layer analog of simulation-based evaluation: define the
contract once, run every implementation through it.

- Round-trip: parse fixture Literate docs (reusing
  `test/resource/`), `put`, `get`, assert model-level equality including
  `interp`, explicit ids, nested assertions, long text blocks.
- Merge matrix: Rules 1–3 and all interp amendment cases (equal /
  one-sided / conflicting / same-id conflict error), asserted identically
  against in-memory union and against `put(merge=True)` — the filesystem
  backend anchoring the chain, since its merge *is* the in-memory union.
- Id-space collisions surface as `AssertionIdConflict` from every
  backend.
- SQLite runs everywhere; Postgres suites gate on `ONYA_TEST_PG_DSN` (17)
  and `ONYA_TEST_PG19_DSN`, the latter also exercising
  `GraphQueryStore` against fixture patterns with known answers.

## Deferred / open questions

- **Views as PGQ element tables** (flagged above): verify against PG 19
  final; drop `onya_edge_hop` for a view if permitted.
- **Skeleton hash in SPEC**: promote v1 to a SPEC appendix only if
  store-to-store federation becomes a goal.
- **Versioning / history**: out of scope. The schema does not preclude a
  later `valid_from/valid_to` treatment (PG 19's temporal `FOR PORTION
  OF` support is noted with interest), but nothing here depends on it.
- **Streaming put for very large graphs** (avoiding full in-memory graph
  before write): the `AssertionStore.add` path covers it in principle;
  a bulk streaming loader is future work.
