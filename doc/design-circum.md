**Design document: circumstances (`onya.circum`)**

A knowledge graph is the place for what a thing *is*: a person's name and birthdate. It is a poor place for what is true of the thing right now and in volume (income this year, readings, billing terms). The graph's extreme denormalization is inefficient for that, and keeping the essence of things apart from their circumstances is worth doing for its own sake. Arguments about which side a fact falls on are fine, and useful.

`onya.circum` keeps the two connected. Circumstances live in relational tables, and the graph stays the source of truth: the tables are a **projection** of it, derived and rebuildable. (The other direction, tables read back into a graph at read time, belongs to this module too and is not built yet. See [design-sidecars.md](design-sidecars.md).)

It is a layer in the sense of SPEC § Reserved vocabulary. The only terms it adds are `@table` and `@column` (below).

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

## What this layer does not do

It reads no tables back into a graph yet, makes no migrations, writes no graph assertions, and does not infer anything the shapes don't say. A graph with no shapes projects to nothing.
