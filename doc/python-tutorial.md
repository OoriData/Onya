# Python quick start

[![PyPI - Version](https://img.shields.io/pypi/v/onya.svg)](https://pypi.org/project/Onya)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/onya.svg)](https://pypi.org/project/Onya)

## Installation

<!--
```bash
pip install amara
```

Or with uv (recommended):

```bash
uv pip install amara
```
-->

Requires Python 3.12 or later. The package is still in early development, so install directly from source:

```bash
git clone https://github.com/OoriData/Onya.git
cd Onya
pip install -U .
```

<!--
pip install git+https://github.com/OoriData/Onya.git
-->

## Command line tool

You can use the built-in CLI to export directly from an Onya Literate (`.onya`) file to the Mermaid diagram format:

```sh
onya convert test/resource/schemaorg/thingsfallapart.onya > out.mmd
```

Then use a site such as https://mermaid.live/ to generate a diagram such as:

![Onya graph of Things Fall Apart, rendered via Mermaid](https://github.com/OoriData/Onya/blob/main/test/resource/schemaorg/thingsfallapart.png)

## Basic Python Usage

Here's a simple example demonstrating the core Onya API. First, let's define a small friendship graph in Onya Literate format:

```
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor
* nickname: Chuks
* age: 28

# Ify [Person]

* name: Ifeoma Obasi
* nickname: Ify
* age: 27
```

Parse this graph and interact with it using the Python API.

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser

# Parse the Onya Literate text into a graph
onya_text = '''
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor
* nickname: Chuks
* age: 28

# Ify [Person]

* name: Ifeoma Obasi
* nickname: Ify
* age: 27
'''

g = graph()
op = LiterateParser()
result = op.parse(onya_text, g)
doc_iri = result.doc_iri
print(f'Parsed document: {doc_iri}')
print(f'Graph has {len(g)} nodes')

# Access nodes and their properties
chuks = g['http://example.org/people/Chuks']
ify = g['http://example.org/people/Ify']

# Get a specific property value
for prop in chuks.getprop('https://schema.org/name'):
    print(f'Name: {prop.value}')

# Add a friendship edge between Chuks and Ify
friendship = chuks.add_edge('https://schema.org/knows', ify)
print(f'Added edge: {friendship}')

# Add nested properties to the friendship (metadata about the relationship)
friendship.add_property('https://schema.org/startDate', '2018-03-15')
friendship.add_property('https://schema.org/description', 'Met at university')

# Add a new property to Ify
ify.add_property('https://schema.org/jobTitle', 'Software Engineer')

# Modify a property in place: nested assertions and the @id stay attached
for prop in chuks.getprop('https://schema.org/age'):
    prop.value = '29'

# Traverse edges
for edge in chuks.traverse('https://schema.org/knows'):
    friend = edge.target
    for name_prop in friend.getprop('https://schema.org/name'):
        print(f'Chuks knows: {name_prop.value}')
    # Access nested properties on the edge
    for date_prop in edge.getprop('https://schema.org/startDate'):
        print(f'  Friends since: {date_prop.value}')

# Find all nodes of a certain type
for person in g.typematch('https://schema.org/Person'):
    for name_prop in person.getprop('https://schema.org/name'):
        print(f'Person in graph: {name_prop.value}')

# Reserialize to Onya literate
from onya.serial.literate import write

write(g)
```

This example demonstrates:
- Parsing Onya Literate format
- Accessing nodes and properties
- Adding edges with nested properties (reified relationships)
- Modifying properties in place
- Traversing the graph
- Querying by type

# Reading values and targets

`getprop()`/`getedge()` give you assertion objects. When you only want what they say, the accessors return plain data, and `label` takes any of the forms above (an `I`, a full IRI string, a CURIE or a bare name):

```python
chuks.values('telephone')          # ['+1 555 0100', '+1 555 0101']   all values, as a list of strings
chuks.targets('knows')             # [<node Ify>, ...]                all edge targets
chuks.one('name')                  # 'Chukwuemeka Okafor' | None      CardinalityError if several
chuks.one_target('employer')       # <node> | None                    CardinalityError if several
```

Assertions are a set, so `values()` and `targets()` are sorted only to be deterministic; the order carries no meaning. `one()` is the strict sibling of `any_prop_value()`, which quietly picks one of several: use `one()` where the data should be single-valued and a second value is a problem worth hearing about. `CardinalityError` carries the node, the label and everything it found. Two identical values are one claim (they merge), so only *distinct* values conflict. The same accessors work on nested assertions (an edge's own properties).

Editing: `prop.value = 'x'` changes a value in place, keeping the property's nested assertions and `@id`, so you don't need remove-then-add. Edits to an edge's `.target` or `.edges` set directly need `g.touch()` so the reverse-edge index (`g.inbound`) is rebuilt; the `add_*`/`remove_*` methods do that for you.

# Merging graphs

Parsing several documents into one graph **accumulates** their assertions — it does
*not* deduplicate. Merge is an explicit, on-demand operation you invoke when you want it,
never something parsing does behind your back:

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser

doc = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Acme [Organization]

* foundingDate: 1999
'''

g = graph()
for _ in range(3):                      # e.g. the same fact extracted from three sources
    LiterateParser().parse(doc, g)

acme = g['http://e.o/Acme']
len(list(acme.getprop('https://schema.org/foundingDate')))   # 3 — three distinct occurrences

g.merge()                               # collapse duplicates, on demand
len(list(acme.getprop('https://schema.org/foundingDate')))   # 1
```

**Until you call `g.merge()`, three parses mean three `foundingDate` assertions.** That is
deliberate: merge follows the identity rules in SPEC § Identity and graph merge (anonymous
assertions with equal skeletons collapse; an `@id` or a differing interpretation holds
genuinely distinct occurrences apart), and applying those rules is the caller's choice, not
a side effect of reading a file. Give two structurally identical assertions distinct `@id`s,
or differing `@as` contracts, and `merge()` keeps them apart.

The same rule applies *within* a single document: two identical `* foundingDate: 1999`
lines in one file are two distinct occurrences until you merge, not a parse-time dedup.
If you want the parse-then-merge in one step, pass `merge=True`:

```python
from onya.serial.literate import read
read(text, g, merge=True)   # equivalent to read(text, g) followed by g.merge()
```

### Reading a knowledge base kept in many files

A KG split across files (say `kg/*.onya.md`) reads into one graph with `read_many`. It takes files, directories (searched recursively for `.onya` and `.onya.md`) or globs, reads in a deterministic order, and merges once at the end if you ask:

```python
from onya.serial.literate import read_many

r = read_many(['kg/', 'extra/*.onya'], merge=True)
r.graph      # the combined graph
r.results    # {Path: ParseResult}: each file's own doc IRI, prefixes and nodebase
```

A spec that matches nothing raises `FileNotFoundError` instead of silently reading nothing, and a parse error names its file. `onya convert` expands directories the same way.

Each `@document` also becomes a node typed `onya:Document` in the graph (as does one read back from a store). When that node is just bookkeeping, for instance in an export you are about to apply to another graph, remove them:

```python
from onya.graph import drop_document_nodes

drop_document_nodes(r.graph)      # [I('http://e.o/doc1'), ...]: the ids removed
```

A document node that carries real assertions (metadata written on the docheader), or that an edge points at, is left in place and is absent from the returned list; `force=True` removes it anyway. The digest ignores these nodes, so it is the same either way.

### Catching typo'd edge targets

An edge to an id that has no node block of its own still parses: Onya Literate allows forward references, and external resources such as an ORCID URL are normal. But a typo (`-> public.unrestriced`) fails the same way, quietly, by minting an empty node. Onya tells the two cases apart by recording which nodes were *declared* (given a block, a type or an assertion, or created with `graph.node()`) and which exist only because an edge named them:

```python
r = read(text, g)
r.dangling                 # [Dangling(target, edge)], one per reference this read left undeclared
str(r.dangling[0])         # 'http://e.o/A --https://schema.org/knows--> http://e.o/Typo'
g.dangling()               # {ids}, graph-wide: a node declared by a later read isn't listed
g['http://e.o/Typo'].declared   # False

# Opt in to a check; allow= lists the targets that are expected to be external
read(text, g, on_dangling='error', allow=['https://orcid.org/'])   # 'ignore' (default) | 'warn' | 'error'
read_many(['kg/'], on_dangling='error')     # judged once, after every file is read
```

`allow` is an IRI prefix, a list of prefixes, or a function of the id, and works the same in `g.dangling(allow=...)`. `on_dangling='error'` raises `DanglingTargetError` (a `ValueError`) listing every offender; the graph is already populated by then. An edge to an assertion `@id` is never dangling. `onya convert` takes the same two options (`--on_dangling=error --allow=https://orcid.org/,https://ror.org/`) and exits non-zero on an error.

Two limits. The flag lives on the in-memory graph, so a graph that has been through a store, or `write` then `read`, no longer remembers which nodes were only referenced. `write` still emits a bare block for them (output unchanged), but will tell you which: pass a set, `write(g, out, placeholders=seen)`, and each placeholder id is added to it, so you can warn, or filter them out of the graph first. And `g.subgraph()` copies a neighborhood, so a node just outside it becomes a bare neighbor, undeclared *in the copy* even if the original declares it. `subgraph(['Ada'], hops=1).dangling()` lists Ada's friend-of-friend until you widen `hops`.

### Finding the line a diagnostic is about

The graph doesn't remember where in a document anything was written (a slot per assertion would cost every graph, diagnosed or not). Ask for it when you want it:

```python
r = read(text, g, track_locations=True)       # also on read_many and LiterateParser
r.locations[assertion]                        # Location(doc_iri, lineno, line, source)
g.locate(assertion)                           # the same, across every tracked read into g (None if unknown)
```

Nodes and assertions at every depth are located; a multi-line value at its first line; a node declared by several blocks at the first. With locations on, diagnostics name the line: `Dangling.lineno`, `Finding.location` (so `str(validate(g))` reads `age on A: 'old' is not a number (at http://e.o/doc:9)`), and the `InterpretationError` that `value_of` raises. Without them they say `(location not tracked)`. `read_many` fills `Location.source` with each file's path. Parse errors about `@id` and `@as` give the line regardless. Locations belong to the objects the read created, so `g.copy()` and anything built through the API have none.

### Reserved vocabulary, and catching `@` typos

Every `@x` in Onya Literate is the IRI `onya:x`, and core reserves a fixed set (the table in SPEC § Reserved vocabulary). Layers add their own terms and register them with `onya.terms.reserve('layer', 'name', ...)`; the registry is `onya.terms.RESERVED`. Parsing accepts any `@x`, because a layer you haven't loaded may define it. To catch typos, audit:

```python
from onya.terms import unknown_reserved_terms
unknown_reserved_terms(g)    # {onya:Calss: [node, ...], onya:sourcee: [assertion, ...]}
```

### Ordered values

Assertions are a set, so the values of a label have no order. When the sequence is the point (address lines, authors, steps), declare the label in the docheader and the parser numbers the occurrences from document order:

```
# @docheader
* @schema: https://levver.io/regkg/
* @ordered: sourceField

# map-co-principalAddress [FieldMapping]
* sourceField: principaladdress1
* sourceField: principaladdress2
* sourceField: principalcity
```

```python
n = read(text).graph['map-co-principalAddress']   # (with the docheader's @document/@nodebase in place)
n.ordered_values('sourceField')   # ['principaladdress1', 'principaladdress2', 'principalcity']
n.ordered_targets('author')       # edges too: nodes, in order
```

The parser stamps a nested `@ordering: 1, 2, 3`; you can also write `@ordering` by hand (gaps are fine, `10, 20, 30`) with no stanza at all. The accessors are strict. A missing or non-integer stamp raises `OrderingError`, and a claim stamped two ways, which is what a `union` of two files that disagree leaves behind, raises `OrderingConflict`. Settle those on purpose with `onya.ordering.resolve(g, 'first')` (or `'last'`, or your own `(assertion, stamps) -> stamp`).

To write the graph back compactly, hand `write` the labels the document declared:

```python
r = read(text, g)
write(g, out, ordered=r.ordered, ...)   # an @ordered stanza and values in order; 1..n stamps left out
```

Without `ordered=` every stamp is written out; both forms read back in the same order. One limitation: repeating a value under an ordered label merges into one assertion, so only one position survives (the stanza warns). Give each occurrence an id to keep both: `* reading -> sicp [=r3]`. The layer is specified in [doc/design-ordering.md](https://github.com/OoriData/Onya/blob/main/doc/design-ordering.md).

### Shapes: what should this graph look like?

Declare classes and properties as nodes (a declaration's id is the class or label IRI it is about), then validate. Shapes report; they never infer a type or change a value, and nothing runs until you ask.

```
# Person [@Class]
# name [@Property]
* @appliesTo -> Person
* @as: text
* @cardinality: 1
# status [@Property]
* @appliesTo -> Person
* @oneOf: active
* @oneOf: closed
```

```python
from onya.shape import validate

report = validate(g)               # shapes in g itself; or validate(g, shapes=shapes_graph)
report = validate(fragment, against=base)   # a proposed change, checked as if merged into base (see below)
for f in report.findings:
    print(f.severity, f.kind, f.node, f.label, f.detail, f.location)   # e.g. one_of ... 'dormant' is not one of [...]
report.ok, report.errors, report.warnings
```

Findings cover `applies_to`, `cardinality` (`1`, `0..1`, `1..*`, `0..*`, `n..m`), `range`, `one_of`, `as`, `ordering`, `undeclared_label` (only for a class marked `@closed: true`), `deprecated` (a warning for a use of a term declared `@deprecated: Use X instead`, optionally with `@replacedBy -> X`), a typo'd `@term`, and, with `dangling=True`, edge targets nothing declares. On the command line:

```
onya validate kg/ --shapes=shapes/ --dangling --allow=https://orcid.org/ --strict
```

To check a **proposed change** (a few nodes, with no declarations and none of the nodes they point at), pass the graph it would join as `against`. Types and cardinality then resolve through the base, and only the findings on the fragment's own nodes come back:

```python
frag = read('# ify [Person]\n* knows -> chuks\n', ...).graph       # alone: `chuks` looks untyped
report = validate(frag, against=base)                              # chuks is a Student in base: no finding
```

When the base lives in a store, `await validate_against_store(frag, store, name)` (from `onya.shape`) reads only the part of it the fragment touches, and `onya validate proposed.onya --against=kg/` (or `--store=sqlite:kg.db --graph=NAME`) does the same from the command line.

Exit status is 2 on errors (warnings too with `--strict`). The vocabulary, rules, and a mapping to SHACL are in [doc/design-shapes.md](https://github.com/OoriData/Onya/blob/main/doc/design-shapes.md).

### Did the knowledge graph change? The content digest

```python
from onya.digest import digest, node_digests

digest(g)                          # 'sha256:9f2c...'
digest(g, nodes=[iri1, iri2])      # just those nodes
node_digests(g)                    # {iri: 'sha256:...'}; compare two versions to see which nodes changed
```

The digest hashes what the graph *says*: equal for one file or three, any order, any prefixes, merged or not, and after a store round trip; different if any value, interpretation, type, edge target, assertion `@id` or `@ordering` changes. `onya:Document` nodes and `@source` assertions are left out by default. `exclude=` *replaces* that default, so to leave out more, extend it: `exclude=DEFAULT_EXCLUDE | {'ex:internalNote'}`. Details in [doc/design-digest.md](https://github.com/OoriData/Onya/blob/main/doc/design-digest.md).

# Data contracts: interpretations

Every Onya value is a string. An **interpretation** is a recorded promise about
how a string is meant to be read — a number, a datetime, a boolean, an IRI,
prose. You attach one with `@as` (or a docheader `@interpretations:` default),
and it rides along on the assertion as data. Nothing checks or converts it while
parsing; you honor the contract *on demand*, at a boundary you choose, through
`onya.interp`.

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser
from onya import interp

text = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* age: 28
* longitude: -105.2705
  * @as: number
* customCode: 0042
  * @as: text
* active: True
  * @as: boolean
'''

g = graph()
LiterateParser().parse(text, g)
chuks = g['http://e.o/Chuks']

def one(label):
    return next(chuks.getprop(label))

# The value is ALWAYS the string; the interpretation is recorded beside it.
age = one('https://schema.org/age')
age.value             # '28' — still a string, always
age.interp            # ONYA_INTERP('number') — baked on by the docheader default

# Honor the contract on demand:
interp.value_of(age)                             # 28  (int — integral)
interp.value_of(one('https://schema.org/longitude'))  # Decimal('-105.2705')
interp.value_of(one('https://schema.org/customCode')) # '0042' — text, leading zero kept
```

Where a value must be a whole number, `integer` is the strict contract: `3`, `-3` and `3_000_000` pass (a single `_` between digits is an ignorable group separator, handy for long figures and unambiguous across locales), while `3.0`, `3e3` and `1,000` don't. `number` is the permissive one.

`number` never passes through a binary `float`: an integer literal becomes an
`int`, anything with a decimal point or exponent becomes a `decimal.Decimal`.
That is what makes the round-trip exact (a `float` would turn `-105.2705` into
`-105.27049999…`) — but it costs one surprise worth meeting on purpose rather
than cold:

```python
lon = interp.value_of(one('https://schema.org/longitude'))  # Decimal('-105.2705')

lon * 2        # Decimal('-210.5410') — fine, Decimal arithmetic
lon + 0.5      # TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'float'

# The fix is yours to make, explicitly — precision loss is now owned by you, the caller:
float(lon) + 0.5   # -104.7705
```

An interpretation your software doesn't have installed is not an error — the
contract just can't be honored here. `value_of` makes you say so:

```python
score = one('https://schema.org/riskScore')     # @as: some group's contract, uninstalled

interp.value_of(score)                # raises UnknownInterpretation
interp.value_of(score, strict=False)  # the raw string — you explicitly waive the contract
interp.unknown_interps(g)             # {I('…/RiskScore'): [<that assertion>]} — what to plug in
```

Checking a graph's contracts produces a **report of findings**, never an
exception. A broken promise is data; the graph stays valid Onya:

```python
report = interp.validate(g)
report.ok       # False — 'active: True' does not check against boolean
print(report)
# https://schema.org/active on http://e.o/Chuks: 'True' is not boolean (expected 'true'|'false')
```

Leniency (accepting `True`, `yes`, `1`) is a *different* contract you register
deliberately, not fine print on the standard `boolean`. And the builder
direction mirrors `value_of`:

```python
from decimal import Decimal
from onya.terms import ONYA_INTERP

interp.set_value(chuks, 'https://schema.org/height', Decimal('1.85'),
                 ONYA_INTERP('number'))
# same as: chuks.add_property('https://schema.org/height', '1.85', interp=ONYA_INTERP('number'))
```

# Finding nodes, and showing them

Label arguments take a full IRI, a CURIE or a bare `@schema` name. `g.search()` is a ranked, typo-tolerant lookup by property value, and `g.inbound()` answers "what points here?" from a reverse index instead of a scan:

```python
hits = g.search('chukwuemka', types=['Person'])        # tiers: exact > prefix > word > fuzzy
hits[0].node_id, hits[0].tier, hits[0].score           # ranked; whether the top hit is clear is your call
[e.origin.id for e in g.inbound(ify, label='knows')]   # nodes with a `knows` edge to Ify
```

`onya.view` turns "show me this thing" into plain data (which fields, which links to follow, in what order) and leaves the rendering to you:

```python
from onya import view

specs = view.load([{'type': 'Person', 'fields': ['name'], 'follow': [{'edge': 'knows', 'show': ['name']}]}])
view.project(g, chuks, specs)      # {'id': ..., 'title': ..., 'fields': [('name', ...)], 'knows': [{...}]}
```

Stores have the same lookups without loading a graph (`await store.search(name, 'chukwuemka', labels=[...])`, `store.nodes_by_type(name, type_iri)`, `await view.project_from_store(store, name, node_id, specs)`). Search and view specs are described in full in the [skill](https://github.com/OoriData/Onya/blob/main/onya-graph.SKILL.md).

# Copies and neighborhoods

`graph.union(other)` *consumes* `other`: its nodes are adopted, and it must not be used afterwards. When you need to keep a graph, or want to try a rewrite you may throw away, work on a copy:

```python
dup = g.copy()                     # deep: new node and assertion objects; same ids, values, interps, @ids, prefixes
dup['http://example.org/people/Chuks'].one('name')   # edits to dup never touch g, and vice versa
g.union(other.copy())              # keeps `other` intact

near = g.subgraph({chuks_iri}, hops=1)   # just a neighborhood, copied; hops=0 is the roots alone
```

`subgraph` follows each node's own edges outward (not edges nested under assertions). An edge that leaves the neighborhood keeps its target as a bare, untyped node, and unknown roots are ignored. It's the in-memory twin of `store.subgraph(name, roots, hops)`, and the two agree.

# Persistence: the store layer

`onya.store` durably keeps named graphs. The protocol is `async`, and the same
code shape works across every backend — you change only the URL you pass to
`connect()`. The golden rule: **merge is the write semantics.** `put(merge=True)`
(the default) into a store that already holds the named graph is a graph union
under the SPEC merge rules — observationally identical to loading both and
calling `graph.union()`.

Start with the filesystem backend. It writes one Onya Literate file per graph, so
you can open the result in any editor — and it is the reference implementation the
SQL backends are checked against:

```python
import asyncio
from onya.store import connect
from onya.serial.literate import read

r = read(open('test/resource/schemaorg/thingsfallapart.onya'))
graph, name = r.graph, r.doc_iri            # name is the graph's @document IRI

async def demo(url):
    async with await connect(url) as store:
        await store.put(name, graph)        # persist (merge=True by default)
        loaded = await store.get(name)      # KeyError if absent
        print('graphs held:', [str(n) async for n in store.names()])
        return loaded

asyncio.run(demo('file:/tmp/onya-graphs'))
```

Move to SQLite by changing nothing but the URL — stdlib, zero added
dependencies, and it adds the `AssertionStore` capability (fine-grained access
without materializing the whole graph):

```python
from onya.store import AssertionStore

async def sqlite_demo():
    async with await connect('sqlite:/tmp/onya.db') as store:
        await store.put(name, graph)
        assert isinstance(store, AssertionStore)
        # stream matching assertions, graph.match() tuple shape
        async for origin, rel, target, annotations in store.match(
                name, 'http://example.org/classics/CAchebe'):
            print(origin, rel, target)
        # load just a neighborhood, out to N hops
        neighborhood = await store.subgraph(name, {'http://example.org/classics/TFA'}, hops=1)

asyncio.run(sqlite_demo())
```

Move to PostgreSQL the same way. It is extras-gated — `pip install
"onya[postgres]"` — and asyncpg is imported only when you use a `postgresql://`
URL (otherwise you get a clear `ImportError`). On PostgreSQL ≥ 19 the store also
satisfies `GraphQueryStore`, exposing SQL/PGQ property-graph queries as an escape
hatch:

```python
from onya.store import GraphQueryStore

async def pg_demo():
    async with await connect('postgresql://user:pass@localhost/onya') as store:
        await store.put(name, graph)
        if isinstance(store, GraphQueryStore):
            rows = await store.graph_table('''
                SELECT * FROM GRAPH_TABLE (onya_base
                    MATCH (a IS resource)-[e IS asserted]->(b IS resource)
                    COLUMNS (a.id AS src, b.id AS dst))
            ''')
```

Three PostgreSQL practicalities:

- **Pool size.** `connect(url, max_size=3)` passes options to `asyncpg.create_pool`, for a pooler that caps connections.
- **Your own pool.** `await PostgresStore.from_pool(pool)` (from `onya.store.postgres`) builds a store on a pool you made, and leaves the pool yours when the store closes. `from_pool(pool, ensure=False)` creates nothing, for a role with data privileges only on a schema someone else provisioned (run `sql/examples/postgres-schema.sql` as the schema's owner; it is idempotent, and needed again after upgrading to 0.6.2, which adds the `onya_graph_rev` table).
- **Has the graph changed?** `await store.version(name)` is a cheap token to compare, so a cache can skip refetching: `if await store.version(name) != last: g = await store.get(name)`. `versions([names])` gives one token for several graphs (say an overlay's authored and runtime graphs).

Merge semantics in action — two overlapping extractions collapse into one:

```python
async def merge_demo():
    async with await connect('sqlite:/tmp/onya.db') as store:
        await store.put('http://e.o/g', read('''
# @docheader
* @document: http://e.o/g
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]
* knows -> Ify
  * since: 2018
''').graph)
        await store.put('http://e.o/g', read('''
# @docheader
* @document: http://e.o/g
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]
* knows -> Ify
  * strength: close
''').graph)                                  # merges: one `knows` edge, both nested props
        g = await store.get('http://e.o/g')
        knows = list(g['http://e.o/Chuks'].traverse('https://schema.org/knows'))
        assert len(knows) == 1               # Rule 2: equal skeletons merged

asyncio.run(merge_demo())
```

For scripts and the REPL, `from onya.store.sync import connect` gives a blocking
facade with the same methods (`with connect(url) as store: store.put(...)`). The
architecture, canonical schema, skeleton hash, and PGQ layer are documented in
[design-persistence-architecture.md](design-persistence-architecture.md).

# Circumstances: tables beside the graph

A graph is the place for what a thing *is*. What is true of it right now, and in volume (a GPA, this term's fees, readings), belongs in tables. `onya.circum` connects the two, in three steps: **project** the graph into tables, **declare** which properties live there, then **augment** (read) and **emit** (write) through that declaration. The design is in [doc/design-circum.md](https://github.com/OoriData/Onya/blob/main/doc/design-circum.md).

### 1. Declare where a property lives

A property that is held in a table gets one `@circumQuery` edge, to a `@Sidecar` node that catalogs the table:

```
# gpa [@Property]
* @appliesTo -> Student
* @as: number
* @circumQuery -> students-db

# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @cardinality: 1
* @circumQuery -> students-db

# students-db [@Sidecar]
* @label: Student records
* @table: student
* @sensitivity: internal
```

Everything else about the property (its type, cardinality, range) is the ordinary [shape](#shapes-what-should-this-graph-look-like). `onya catalog kg/` lists every sidecar and the properties that point at it.

### 2. Project the graph into tables

`from_shapes` reads the shapes and derives the tables, so you don't list columns by hand:

```python
import sqlite3
from onya.circum import from_shapes, ddl, materialize

conn = sqlite3.connect('students.db')
p = from_shapes(g, 'http://e.o/Student')       # also projects Person, because counselledBy points at it
print(ddl(p))                                  # the CREATE TABLEs (the same as `onya project kg/ Student`)
report = await materialize(conn, p, g)         # report.inserted, .updated, .unchanged, .deleted
```

`materialize` is idempotent: a second run over an unchanged graph reports every row `unchanged`. Every table gets an `updated` column, which a row only changes when its values do. Tables are created if missing and never altered, and a table that no longer matches the projection raises `CircumError` rather than being guessed at.

### 3. Read: `augment` gives a view

Later you load a graph that doesn't hold the table's values (they have been moved out, or never were in it). `augment` returns a **new graph** with them filled in:

```python
from onya.circum import Registry, augment, strip, is_view, table_resolvers, table_writers
from onya.shape import validate

reg = Registry()
reg.resolvers.update(table_resolvers(p))       # one resolver per property, derived from the projection
reg.writers.update(table_writers(p))

view = await augment(g, registry=reg, conn=conn)     # g is untouched
is_view(view), is_view(g)                            # (True, False)
```

Everything the view adds carries `@method -> students-db` and an `@asOf` (the row's `updated`), so you can always tell it from what the graph says itself. `strip(view)` removes exactly that, and `digest(strip(view)) == digest(g)`. A view is never persisted: `store.put` refuses one.

A view can be incomplete in a way the pure graph can't. Dede has no row in the table, and `counselledBy` is `@cardinality: 1`:

```python
validate(g).findings                           # []: the graph never claimed a counsellor for Dede
[str(f) for f in validate(view).findings]
# ['error cardinality: http://e.o/dede http://e.o/counselledBy: has 0, declared 1']
```

`augment(g, registry=reg, conn=conn, ids=[chuks])` looks up only those nodes, and `validate` then reports gaps only for them. To keep a sidecar private, give `Registry(policy=fn)` a function `fn(viewer, sensitivity)`, and pass `viewer=` to `augment`.

### 4. Write: `emit` moves values into the table

Give a node a circum value in the graph, and `emit` writes it to the table, then removes it from the graph (table first, so a fact is never in neither place):

```python
from onya.circum import emit

g['http://e.o/dede'].add_property('http://e.o/gpa', '3.9')
g['http://e.o/dede'].add_edge('http://e.o/counselledBy', g['http://e.o/adat'])
report = await emit(g, ['http://e.o/dede'], registry=reg, conn=conn)
len(report.moved), report.review               # (2, []): review lists what it left in the graph, and why
```

`emit` is idempotent and never deletes. A new row is created only if the table can take it: if other columns are `NOT NULL`, the call raises a `CircumError` naming them, because a node that breaks its own `@cardinality: 1` has nothing valid to insert.

### Ledgers: one value per period

A property can hold several values for a node, told apart by a nested label. Declare the label with `@qualifier` (it becomes the key) and any that just rides along with `@attribute`:

```
# compensation [@Property]
* @appliesTo -> Person
* @as: number
* @cardinality: 0..*
* @circumQuery -> payroll
* @qualifier -> period
* @attribute -> unit

# period [@Property]
* @as: text

# unit [@Property]
* @as: text

# adat [Person]
* compensation: 5000
  * period: 2026-Q1
  * unit: month
* compensation: 5000
  * period: 2026-Q2
  * unit: month
```

The projection's `person_compensation` table is keyed `(person_id, period)`, so the same amount in two periods is two rows, and a value with no `period` is one row with `''`. `augment` shows the values with their nested `period` and `unit`, and `emit` moves them. A value whose nested assertions are anything else (a note, say) stays in the graph for review. A key given two different values is a `CircumError` rather than an overwrite, because a changed amount is something a person should look at. In a hand-written resolver or writer the same data is `Text.qualifiers` and `Text.attributes` (`{label IRI: text}`).

### When the derived functions aren't enough

`table_resolvers` and `table_writers` only know tables that `from_shapes` built. A sidecar in Redis, MongoDB or someone else's database gets a function you write, registered by the property's IRI. It receives every requested node at once and returns `{subject IRI: [Edge | Text]}`:

```python
from onya.circum import Edge, Text

@reg.resolver('http://e.o/gpa')
async def gpa(subjects, ctx):                  # ctx.conn is whatever you passed to augment
    found = await ctx.conn.mget([f'gpa:{s}' for s in subjects])      # e.g. redis.asyncio
    return {s: [Text(v)] for s, v in zip(subjects, found) if v}
```

The same goes for a property shared by two projected tables (say `email` on both `Student` and `Person`): Onya won't guess which table is meant, and the derived resolver raises `CircumError: http://e.o/email is held in several tables ['person', 'student']: write its resolver or writer by hand`. The other properties keep their derived functions; register yours for that label alone:

```python
@reg.resolver('http://e.o/email')
async def email(subjects, ctx):
    found = {}
    for table in ('student', 'person'):        # table names are literals here, never taken from the graph
        marks = ', '.join('?' * len(subjects))
        for id_, v in ctx.conn.execute(f'SELECT id, email FROM {table} WHERE id IN ({marks})', list(subjects)):
            if v is not None:
                found[id_] = [Text(v)]
    return found
```

A writer is the same shape, `async def (rows, ctx)` with `rows` as `{subject IRI: [Edge | Text]}`, registered with `@reg.writer(label)`. Keep it idempotent, and stamp the row's `updated` so `@asOf` stays honest.

One rule for both: SQL comes from your code, never from the graph. `@table`, `@column` and `@queryDetail` text in a graph is data and is never spliced into a query.

# Visualization / export

`onya.viz` projects a graph into other tools' formats for visualization and analysis
(not a serialization of Onya itself — that's `onya.serial`):

- **Graphviz (DOT)**: `from onya.viz import graphviz` → `graphviz.write(g, out=f)` (see `demo/graphviz_basic/`)
- **Mermaid (flowchart)**: `from onya.viz import mermaid` → `mermaid.write(g, out=f)` (see `demo/mermaid_basic/`; quick viewing via [Mermaid Live Editor](https://mermaid.live/))
- **networkx** (analytics, not just diagrams): `from onya.viz import nx` — see `demo/nx_analytics/`

(`onya.serial.{graphviz,mermaid,nx}` still import as deprecated aliases.)

