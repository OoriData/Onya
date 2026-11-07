**Design document: circumstances (`onya.circum`)**

A knowledge graph is the place for what a thing *is*: a person's name and birthdate. It is a poor place for what is true of the thing right now and in volume (income this year, readings, billing terms). The graph's extreme denormalization is inefficient for that, and keeping the essence of things apart from their circumstances is worth doing for its own sake. Arguments about which side a fact falls on are fine, and useful.

`onya.circum` keeps the two connected. Circumstances live in relational tables, and the graph stays the source of truth: the tables are a **projection** of it, derived and rebuildable. The other direction, circumstances held in tables but shown in the graph at read time, belongs to the same module (see [Reading circumstances](#reading-circumstances-sidecars-augment-emit) below, and [design-sidecars.md](design-sidecars.md) for the pattern).

It is a layer in the sense of SPEC § Reserved vocabulary. The terms it adds are `@table` and `@column` (below), and, for the read side, `@Sidecar`, `@System`, `@system`, `@circumQuery`, `@queryDetail`, `@sensitivity` and `@retention`. It also uses the core `@method` and `@asOf`.

## Deriving a projection from shapes

```python
from onya.circum import from_shapes, ddl, materialize

p = from_shapes(g, 'https://example.org/Person')   # shapes in g, or shapes=other_graph
print(ddl(p))                                      # or ddl(p, 'sqlite')
report = await materialize('sqlite:circumstances.db', p, g)
```

The [shape layer](design-shapes.md) already says what a class's properties are, so the projection reads them rather than being listed by hand:

| Shape fact | Column fact |
|---|---|
| `@as: integer` / `number` / `datetime` / `boolean` | `integer` / `numeric` / `timestamptz` / `boolean` |
| no `@as`, or one the projection doesn't know | `text`. It never guesses a type from the values. |
| `@cardinality: 1` | `NOT NULL` |
| `@cardinality: 0..1`, or none declared | nullable |
| `@cardinality` with a maximum above 1 | a child table `<table>_<label>(<table>_id, value)`; with `array_columns=True`, an array column (PostgreSQL only) |
| `@range -> Class` | `<label>_id`, a foreign key to that class's table. The class is projected too. |
| `@ordered: true` | an `ordinal` column in the child table, from `@ordering` |
| `@oneOf` (single text value) | a `CHECK (col IN (...))` |
| `@table`, `@column` on a declaration | the table or column name, in place of the one derived from the class or label |

Names are the local part of the IRI in `snake_case` (`addressLine` is `address_line`); a reserved word is quoted. Two properties that derive the same column name are an error, answered with `@column`. A property with no `@appliesTo` names no class, so it gives no column. Properties of a superclass are columns of its subclasses' tables, and a subclass's nodes are rows of the superclass's table, as `@subClassOf` is closed over for validation. A `@range` with more than one class gives a plain text column and no foreign key.

Foreign key order is **derived from the references**, not from the order of the file: `ddl` and `materialize` create each table after the ones it references. All foreign keys are `DEFERRABLE INITIALLY DEFERRED`, so row order inside a run doesn't matter and a table can reference itself. Tables that reference each other in a cycle are an error, unless the projection is built with `foreign_keys=False`.

A projection can still be written by hand, for exceptions: `Projection([Table(...)])`, with `Column`s of kind `id`, `value`, `edge` or `ordinal`.

## Rows

`rows(p, g)` gives `{table: [tuples]}`, sorted by key. Values are read through their interpretation (a value's own `@as` wins over the property's default), so a column holds an `int`, a `Decimal`, a `bool`, or an aware UTC datetime (a date alone is midnight UTC). All the problems are collected into one `CircumError`, each naming its node and line (when the graph tracked locations):

- a value that doesn't fit its column (`@as: integer` with `seven`);
- a required value (`@cardinality: 1` or `1..*`) the node lacks;
- a single-valued label (including one with no declared `@cardinality`) with more than one value;
- stamps that conflict, under an ordered label;
- an edge to a node that is in no table (checked on a full projection; with `nodes=`, the database's foreign key decides).

## Writing

`materialize(target, p, g)` runs in one transaction. It creates the tables that are missing, then inserts, updates and deletes until the tables hold exactly `rows(p, g)`, and returns a `Report` (`created`, `inserted`, `updated`, `unchanged`, `deleted`, `graph_digest`, and per-table counts). The rows are built and checked first, so a bad value writes nothing. A second run over an unchanged graph reports every row `unchanged`.

`target` is `'sqlite:path'`, `'postgresql://...'` (asyncpg, `pip install "onya[postgres]"`), or an open `onya.store` store, `sqlite3.Connection` or asyncpg pool. The backends are deliberately thin: SQLite through the stdlib, PostgreSQL through asyncpg. Tables are **created if missing and never altered**; after changing a projection's columns, drop the tables. Migrations are out of scope.

`onya project FILESPEC CLASS [--shapes=] [--to=URL]` does the same from the command line, printing the DDL when there is no `--to`.

### Provenance and incremental runs

Each run adds a row to `onya_circum_runs` (`run_at`, `projection`, `graph_digest`, the four counts). The digest is [`onya.digest.digest(g)`](design-digest.md) of the whole graph, so "which graph version produced these tables" is a lookup, and "are the tables current?" is `digest(g) == (await last_run(target, p))['graph_digest']`.

`materialize(..., nodes=ids)` re-projects only those nodes: rows owned by other nodes are left alone, and rows owned by a listed node that no longer exists are deleted. Pass the nodes whose entry in `node_digests` changed between two versions. The recorded digest is still the whole graph's.

## Authored and runtime graphs

Authored files and runtime assertions should live in **separate named graphs** of a store, so that re-importing a file never clobbers a decision made at runtime. Project the combination:

- `store.union([...])` keeps every value. A disagreement on a single-valued label then breaks its `@cardinality`, and `rows` refuses to pick for you. Use it when the graphs should agree and a disagreement is a bug.
- `store.overlay([...], single_cardinality=single_valued(shapes), precedence=[...])` treats the graphs as ordered layers and lets the winner replace the others, returning the audit trail of what was shadowed. Use it when a layer is supposed to override. `single_valued(shapes)` lists the labels whose `@cardinality` allows one value.

## Reading circumstances: sidecars, `augment`, `emit`

Some facts are **declared** in the graph but **held** elsewhere: a counsellor assignment in the university database, a fee in the billing system. `augment` makes them appear in a *view* of the graph, as if written there; `emit` moves them out of the graph and into where they live. One declaration drives both.

```markdown
# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @cardinality: 1
* @circumQuery -> counsellor-assignments
  * @queryDetail: counsellor_for_students

# counsellor-assignments [@Sidecar]
* @label: Counsellor assignments
* @system -> onya-uni-db
* @table: counsellor
* @sensitivity: internal
* @retention: life of the enrolment plus seven years
```

A circum property is an ordinary `@Property` with one `@circumQuery` edge, to the `@Sidecar` that holds its values. The sidecar node is also the catalog entry (`onya catalog` lists it, with the properties that point at it, computed from those edges and never written). Sidecars are keyed by subject IRI, implicitly.

`@queryDetail` is **opaque**: a name or token handed to the resolver. It is never executable text, because a graph travels (git, an LLM's context, other teams) and query text in one is both a leak and an injection surface. The application writes its own, parameterized, query; a resolver may ignore `@queryDetail` and build one from `@table` and the shapes.

### Resolvers and `augment`

```python
reg = Registry(policy=lambda viewer, sensitivity: viewer.staff or sensitivity == 'public')

@reg.resolver('https://example.org/counselledBy')
async def counselled_by(subjects, ctx):          # every subject at once: one query per property
    rows = await ctx.conn.fetch(SQL[ctx.detail], subjects)
    return {r['iri']: [Edge(r['counsellor'], node=Node(('Person',), {NAME: r['name']}), as_of=r['updated'])]
            for r in rows}

view = await augment(g, registry=reg, viewer=me, conn=conn)       # a new graph; g is untouched
```

A resolver returns `{subject IRI: [Edge | Text]}`. An `Edge` to a node the graph lacks carries a `Node` (the **circum node**) with the few facts it needs, so the view has no dangling edge. A target already in the graph is not re-typed. A resolver may be a plain function or a coroutine.

Everything the view adds carries `@method -> <sidecar>` and `@asOf` (the row's own time, else the retrieval time); a node the view creates also carries `@method` itself. The view also says that it is one: each sidecar it consulted gets an `@asOf` with a nested `@method` pointing back at the sidecar itself, so a view that is written out as text and read back is still recognised (`onya.circum.is_view`). `strip(view)` removes exactly that, and nothing else, so `digest(strip(view)) == digest(g)`. A view is never persisted: every `onya.store` backend's `put` raises `CircumDerivedError` for a graph holding sidecar-derived assertions.

Order of events in `augment`: declarations are checked, then the viewer's access to **every** sidecar involved (`policy(viewer, sensitivity)`; none means allow all), then each resolver runs. A refusal (`CircumAccessDenied`) names the sidecar and the property and runs nothing. A resolver that raises fails the call (`on_error='finding'` returns the view with the failure in `view_findings(view)` instead); one that returns rows for a subject it wasn't asked about is refused.

Because the graph can be incomplete only as a view, `validate` skips the `@cardinality` minimum of a circum property on an ordinary graph, and checks it on a view: a student with no counsellor row is a finding on the view, not a flaw in the graph. The marker above is what tells `validate` which it is, so the result is the same before and after a text round trip. A view limited with `ids=` is incomplete only for the nodes it was asked about: each of those carries the same `@asOf` / `@method -> <sidecar>` mark, and `validate` checks the minimum on them alone. A property whose resolver failed (`on_error='finding'`) is not reported as missing either; the failure is the finding. The graph can't say which of two properties in one sidecar failed, so if that happens `augment` warns once, naming every such property, that the view, once written out and read back, would report the failed property as missing.

### `emit`

```python
report = await emit(g, touched=[iri], registry=reg)    # report.moved, report.review
```

For each touched node, `emit` hands the assertions whose label has a `@circumQuery` to the property's registered **writer** as `{subject IRI: [Edge | Text]}`, then removes them from `g`: sidecar first, graph second, so a fact is never in neither place. Writers must be idempotent, since a crash between the two steps leaves a fact in both and the retry writes it again. Nothing is removed until every writer has succeeded.

It leaves in place, naming them in `report.review`, assertions with an `@id` or nested assertions (removing one would take them along, and a row elsewhere may point at it), and ignores what came from a sidecar. A circum label with no writer, or a viewer the policy refuses, raises before anything is written. `g` is edited in place: pass `g.copy()` for a dry run. A target node an emitted edge pointed at stays in the graph.

## What this layer does not do

It makes no migrations, does no caching and has no staleness policy, and does not infer anything the shapes don't say. It opens no database connection for the read side: resolvers and writers are the application's, and receive what it passes as `conn`. A graph with no shapes projects to nothing.
