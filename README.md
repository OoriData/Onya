**Onya** is a knowledge graph data model and expression format, with a Python
implementation. This repository combines the [data model and format spec](SPEC.md) with the Python implementation.
Onya grew out of a long-standing observation from the RDF
community: the triple is too expressively weak in practice. Quads and named
graphs are insufficient RDF-based workarounds; property graphs solve it for relationships but
abandon the web: no IRIs, no shared vocabularies, no dereferenceability.

Onya takes annotatable, first-class relationships from the property graph
world and keeps what RDF got right: IRIs throughout, and vocabulary reuse
(schema.org works out of the box). Its key structural idea is *recursive
assertion*: every edge and property can itself carry edges and properties,
uniformly, with no RDF-style reification ceremony. Qualified values, relationship
metadata, and n-ary relations work well through the same mechanism.

The Onya Literate format is Markdown-native, so easy for humans to write, and
easy for LLMs to emit and consume, which makes Onya a natural interchange
for LLMOps (extracted knowledge, agent context and more).

Note: Using our provided [onya-graph.SKILL.md](onya-graph.SKILL.md) with your favorite AI coding agent is a good way to automate Onya authoring and explore the format. Try providing a text document and asking it to generate a graph therefrom.

## The model in thirty seconds

Here's a complete, valid knowledge graph, first visualized:

![Onya friendship example](onya-friendship.svg)

Then in Onya Literate format:

```
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor
* knows -> Ify
  * startDate: 2018-03-15
  * description: Met at university

# Ify [Person]

* name: Ifeoma Obasi
* jobTitle: Software Engineer
```

Notice how the `knows` edge carries its
own assertions: a start date and a description *of the relationship itself*.
No reification ceremony, no separate "edge properties" mechanism with its own
rules. Every edge and every property can carry further edges and properties,
recursively, through one uniform mechanism. Node IDs resolve against
`@nodebase`; bare labels and types resolve against `@schema`, so schema.org
(or any vocabulary) works out of the box.

# How Onya relates to its conceptual neighbors

|                              | RDF 1.1        | RDF 1.2 / RDF-star   | Property graphs (Neo4j, GQL) | Onya |
|------------------------------|----------------|-----------------------|------------------------------|------|
| Identifiers                  | IRIs           | IRIs                  | Opaque internal IDs          | IRIs throughout |
| Shared vocabularies (e.g. schema.org) | Native | Native               | Ad hoc strings               | Native |
| Metadata on relationships    | Reification ceremony | Triple terms    | Edge properties              | Nested assertions |
| Metadata on *property values* | Reification ceremony | Awkward         | Not expressible              | Same nested assertions |
| Edges from a property/edge   | No             | No                    | No                           | Yes — the mechanism is uniform |
| Assertion identity           | Statements are types (set semantics) | Contested (type vs. occurrence) | Edges are instances | Assertions are instances |
| Blank nodes                  | Yes            | Yes                   | —                            | None |
| Value types in core          | XSD literal system | XSD literal system | Implementation-defined       | Strings; data contracts layered above (`@as`) |
| Human-writable serialization | Turtle         | Turtle-star           | None standard                | Markdown-native |
| Query orientation            | SPARQL (aggregate/pattern) | SPARQL-star | Cypher/GQL (path-first)   | Traversal API; path language planned |

Two rows carry the heart of the distinction. Onya assertions are *occurrences*
by construction — each edge or property is an instance, sidestepping the
type-versus-occurrence ambiguity that complicated RDF-star standardization.
And the mechanism is uniform all the way down: a property value can carry
edges (a temperature with a `measurementMethod` link), which has no clean
analogue in either the RDF or property-graph lineage.

# Values are strings, with data contracts layered above

Every Onya value is a string, and the string layer is unconditionally valid:
`birthDate: spring 1958` is welcome exactly as written. Onya deliberately has
no built-in type system — in the XSD/OWL lineage, types describe how computers
store things, not what the things are, and data models built on them end up
rejecting true statements that don't fit the machinery.

Instead, an author may attach an **interpretation**: a recorded promise about
how a value is meant to be read, declared inline with `@as` or once per
property label in the docheader. Contracts are honored at boundaries, on
demand — never enforced ambiently by the model:

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser
from onya import interp

onya_text = '''
# @docheader

* @document: http://example.org/people-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/
* @interpretations:
    * age: number

# Chuks [Person]

* age: 28
* birthDate: spring 1958
  * @as: datetime
'''

g = graph()
LiterateParser().parse(onya_text, g)
chuks = g['http://example.org/people/Chuks']

age = next(chuks.getprop('https://schema.org/age'))
age.value               # '28' — the model always stores the string
interp.value_of(age)    # 28 — the contract, honored where you ask

report = interp.validate(g)
report.ok               # False: 'spring 1958' fails its datetime contract —
print(report)           # a reported finding, never a parse error or rejection
```

An interpretation your software doesn't recognize is data, not an error: it
parses, merges, and round-trips untouched. The built-in starter set (`number`,
`datetime`, `boolean`, `iri`, `text`) is deliberately modest, and the plugin
registry lets any community define its own. If you're arriving from data
engineering, note that this is the *value-level* slice of "data contract" —
shape, ownership, and SLAs would be further layers, deliberately not this one.
The design rationale is in
[doc/design-interpretations-strings-vs-typing.md](doc/design-interpretations-strings-vs-typing.md).

# Python quick start

[![PyPI - Version](https://img.shields.io/pypi/v/onya.svg)](https://pypi.org/project/Onya) [![PyPI - Python Version](https://img.shields.io/pypi/pyversions/onya.svg)](https://pypi.org/project/Onya)

Requires Python 3.12 or later. The package is still in active development, so you can install directly from source:

```
git clone https://github.com/OoriData/Onya.git
cd Onya
pip install -U .
```

The base install is dependency-light. Optional extras pull in peripherals only when you need
them: `pip install "onya[nx]"` for the networkx projection (analytics) and
`pip install "onya[postgres]"` for the PostgreSQL store backend.

Parse a small graph in Onya Literate format, then work with it, including adding assertions on an edge:

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser, write

onya_text = '''
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor

# Ify [Person]

* name: Ifeoma Obasi
'''

g = graph()
LiterateParser().parse(onya_text, g)

chuks = g['http://example.org/people/Chuks']
ify = g['http://example.org/people/Ify']

# Edges are first-class: they can carry their own assertions
friendship = chuks.add_edge('https://schema.org/knows', ify)
friendship.add_property('https://schema.org/startDate', '2018-03-15')

# Traverse, reading nested assertions along the way
for edge in chuks.traverse('https://schema.org/knows'):
    for name in edge.target.getprop('https://schema.org/name'):
        print(f'Chuks knows: {name.value}')
    for since in edge.getprop('https://schema.org/startDate'):
        print(f'  Friends since: {since.value}')

# Round-trip back to Onya Literate
write(g)
```

## Persistence

`onya.store` keeps graphs across sessions and processes. It is a peripheral, not
an organ: the core model never imports it, and a store is *correct* exactly when
a round trip through it is indistinguishable from an in-memory graph union —
`put(merge=True)` unions with any stored graph under the SPEC merge rules. Three
backends ship, all behind one async protocol and selected by URL scheme:

```python
import asyncio
from onya.store import connect
from onya.serial.literate import read

r = read(open('test/resource/schemaorg/thingsfallapart.onya'))
g, name = r.graph, r.doc_iri

async def main():
    # Filesystem — one Onya Literate file per graph; the default, and the testing fake.
    async with await connect('file:/tmp/onya-graphs') as store:
        await store.put(name, g)                 # merge=True by default
        again = await store.get(name)            # -> onya.graph.graph
        print([str(n) async for n in store.names()])

    # SQLite — stdlib, zero added dependencies; also an AssertionStore.
    async with await connect('sqlite:/tmp/onya.db') as store:
        await store.put(name, g)
        async for origin, rel, target, ann in store.match(name, 'http://example.org/classics/CAchebe'):
            print(origin, rel, target)

    # PostgreSQL — pip install "onya[postgres]"; SQL/PGQ property graphs on PG >= 19.
    async with await connect('postgresql://user:pass@localhost/onya') as store:
        await store.put(name, g)

asyncio.run(main())
```

A blocking facade (`from onya.store.sync import connect`) mirrors the API with
`with`/plain calls for scripts and REPL use. Design and schema details are in
[doc/design-persistence-architecture.md](doc/design-persistence-architecture.md).

## Visualize / export

The CLI converts Onya Literate (`.onya`) files to diagram formats:

```
onya convert test/resource/schemaorg/thingsfallapart.onya > out.mmd        # Mermaid (default)
onya convert test/resource/schemaorg/thingsfallapart.onya --dot > out.dot  # Graphviz DOT
```

View Mermaid output instantly at [mermaid.live](https://mermaid.live/), producing e.g.:

[![Onya graph of Things Fall Apart, rendered via Mermaid](test/resource/schemaorg/thingsfallapart.png)](https://github.com/OoriData/Onya/blob/main/test/resource/schemaorg/thingsfallapart.png)

### networkx projection + analytics round trip

For graph analytics, `onya.serial.nx` (extras-gated: `pip install "onya[nx]"`) projects a graph
into a `networkx.MultiDiGraph`, and `write_back` records results — centrality, community, any
networkx output — back into the Onya graph as typed, merge-safe assertions. The projection is
lossy by design (first-level structure) and reflects the graph as-is; call `g.merge()` first
for a normalized view.

```python
import networkx
from onya.serial import nx
from onya.terms import ONYA_INTERP

mg = nx.to_networkx(g)                                          # -> networkx.MultiDiGraph
scores = networkx.betweenness_centrality(mg)
nx.write_back(g, 'https://example.org/betweenness', scores, interp=ONYA_INTERP('number'))
# scores are now first-class Onya assertions: queryable via g.select, merge-safe on store.put
```

See [`demo/nx_analytics/`](demo/nx_analytics/) for a runnable end-to-end example.

For the full API walkthrough — modifying and removing properties, querying by
type, data contracts and validation, explicit graph merge, the serializer
modules and their options — see
[doc/python-tutorial.md](doc/python-tutorial.md).

# Acknowledgments

<table><tr>
  <td><a href="https://oori.dev/"><img src="https://www.oori.dev/assets/branding/oori_Logo_FullColor.png" width="64" /></a></td>
  <td>Onya is primarily developed by the crew at <a href="https://oori.dev/">Oori Data</a>. We offer LLMOps, data pipelines and software engineering services around AI/LLM applications.</td>
</tr></table>

# Background

Onya is based on experience from developing [Versa](https://github.com/uogbuji/versa) and also working on [the MicroXML spec](https://dvcs.w3.org/hg/microxml/raw-file/tip/spec/microxml.html) and implementations thereof.

The URL used for metavocabulary is [managed via purl.org](https://purl.archive.org/purl/onya/vocab).

The name is from Igbo "ọ́nyà", web, snare, trap, and by extension, network. The expanded sense is ọ́nyà úchè, web of knowledge.

# Contributing

Contributions welcome! We're interested in feedback from the community about what works and what doesn't in real-world usage. To get help with the code implementation, read [CONTRIBUTING.md](CONTRIBUTING.md).

# License

- **Code** (Python library): Apache 2.0 - See [LICENSE](LICENSE)
- **Specification** (SPEC.md): [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) - See [LICENSE-spec](LICENSE-spec)

The specification is under CC BY 4.0 to encourage broad adoption and derivative work while ensuring attribution. We want the format itself to be as open and reusable as possible, allowing anyone to create implementations in any language or adapt the format for their specific needs.

# Related Work

- [networkx](https://github.com/networkx/networkx): Network Analysis in Python — Onya bridges to it directly via `onya.serial.nx` (projection + analytics write-back)
- [Apache AGE](https://github.com/apache/incubator-age): PostgreSQL Extension for graphs. ANSI SQL & openCypher over the same DB.
