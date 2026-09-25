# SQL examples

**Example only.** Onya creates and upgrades its own store schema whenever a store is opened, so
most deployments never need anything here. These files are starting points for setups where schema
changes go through your own migration tooling (Alembic, Flyway, sqitch, a DBA). Adapt them to your
environment; they carry no compatibility promise across onya versions, and nothing checks them
against the live schema.

| File | What it is |
|------|------------|
| `postgres-schema.sql` | The full PostgreSQL store schema: core tables and indexes, the version keys onya checks on open, the `onya_graph_prefix` table, and the `pg_trgm` search objects, plus commented-out grant examples. Every statement is idempotent, so it doubles as an upgrade script. Leaves out the SQL/PGQ property graphs onya creates on PostgreSQL 19+. |
| `regenerate.py` | Rewrites `postgres-schema.sql` from onya's own schema definition. Run it after installing the onya version you want the example to match: `python sql/examples/regenerate.py`. |

## Applying it

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/examples/postgres-schema.sql
```

Run it as a role that can create tables, functions, and (for indexed search) the `pg_trgm`
extension, such as the schema owner. Without `pg_trgm`, search still works; it just ranks in Python, unindexed.

## Backfilling prefixes

Graphs stored before prefix persistence have no prefixes recorded, and SQL can't recover them.
To backfill from the source document, put a graph that carries only prefixes. It adds prefix rows
and leaves the data untouched:

```python
from onya.graph import graph
from onya.serial import literate

src = literate.read(open('my-graph.onya')).graph
await store.put(name, graph(prefixes=src.prefixes))
```

## Least-privilege application roles

Once the schema is provisioned, the application can connect as a role with only data
privileges (see the commented grants at the end of the script). On open, onya checks what
already exists and runs DDL only for what's missing, so such a role never needs CREATE. If
something is missing and the role can't create it, opening fails with a `StoreError` that names
the missing objects. Missing search objects never fail the open; search just ranks in Python.
