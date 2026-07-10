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

![Running MLX-LM generate within Python](test/resource/schemaorg/thingsfallapart.png)

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

# Modify a property by removing the old one and adding a new one
age_props = list(chuks.getprop('https://schema.org/age'))
for prop in age_props:
    chuks.remove_property(prop)
chuks.add_property('https://schema.org/age', '29')

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
- Modifying properties
- Traversing the graph
- Querying by type

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

# Visualization / export

Onya includes simple serializers to help you visualize graphs:

- **Graphviz (DOT)**: `from onya.serial import graphviz` → `graphviz.write(g, out=f)` (see `demo/graphviz_basic/`)
- **Mermaid (flowchart)**: `from onya.serial import mermaid` → `mermaid.write(g, out=f)` (see `demo/mermaid_basic/`; quick viewing via [Mermaid Live Editor](https://mermaid.live/))

