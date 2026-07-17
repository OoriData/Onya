---
name: onya-graph
description: Author Onya knowledge graphs in the Onya Literate (.onya.md) Markdown format — docheader, node blocks, properties, edges, single/multi types, CURIEs, nested/reified assertions, assertion identifiers (@id), data-contract interpretations (@as), long text, graph merge/identity, validation by parsing, Mermaid/Graphviz export, and pointers to the onya.store persistence layer. Use when creating, editing, extracting, or reviewing Onya graphs (e.g. turning a document into a .onya knowledgebase, or hand-writing/fixing one).
---

# Authoring Onya Graphs

## Purpose

Onya is a knowledge-graph model — nodes, edges, properties, all identified by IRIs — with a human-friendly Markdown serialization called **Onya Literate**. Prefer the **`.onya.md`** extension: it is Markdown, so Markdown-aware tools (GitHub, editors, diff viewers) render and fold it correctly with no Onya support, while a bare `.onya` shows as plain text. This skill is how to author, fix, and validate these files, including the common task of extracting a knowledge graph from a source document.

The model is deliberately tiny: a **node** has an id (IRI), a set of types, and a set of assertions; an **assertion** is either a **property** (label IRI → string value) or an **edge** (label IRI → target node). Assertions are themselves anonymous nodes, so **any assertion can carry its own nested assertions** — that is how Onya does relationship metadata, qualified values, and n-ary relations without extra machinery. Authoritative reference: [the Onya Model Specification](https://github.com/OoriData/Onya/blob/main/SPEC.md). Treat the code and spec as source of truth over this summary.

## When to use / not use

- **Use** when the deliverable is a `.onya` file: extracting a KG from prose, hand-authoring one, or repairing/reviewing an existing graph.
- **Not** for the Python graph API itself (`onya.graph`, `LiterateParser`, traversal, merge internals) — that's library work; see the README example and `pylib/`. This skill covers the *authoring* surface and uses the parser only to validate. The *Merging & identity* and *Persistence* sections below are orientation for downstream consumers, not a full API reference.

## Format essentials

A file is a `# @docheader` block followed by `# NodeID [Type]` node blocks.

```
# @docheader

* @document: http://example.org/classics/things-fall-apart   <!-- IRI of THIS document (required) -->
* title: Things Fall Apart knowledgebase                     <!-- plain assertion → attaches to the document node -->
* @nodebase: http://example.org/classics/                    <!-- base for node IDs; defaults to @document -->
* @schema: https://schema.org/                               <!-- base for BOTH property labels AND types (you almost always want this) -->
* @language: en

# TFA [Book]                <!-- node id `TFA` → @nodebase+TFA ; type `Book` → @schema+Book -->

* name: Things Fall Apart   <!-- property: label `name` → @schema+name, value is the string -->
* isbn: "9781841593272"     <!-- quote values with leading zeros / special chars so they stay strings -->
* author -> CAchebe         <!-- edge: `->` (or the Unicode arrow →) points to another node id -->
* publisher -> Heinemann

# CAchebe [Person]

* name: Chinua Achebe
* birthDate: "1930-11-16"
* birthPlace -> Ogidi
```

Resolution rules — keep these straight, they're the #1 source of mistakes:

| Position | Expanded against | Example → IRI |
|---|---|---|
| Node id (`# Foo`, edge target `-> Foo`) | `@nodebase` (else `@document`) | `CAchebe` → `…/classics/CAchebe` |
| Property / edge label (`name:`, `author ->`) | `@schema` | `name` → `https://schema.org/name` |
| Type (`[Person]`) | `@schema` (or `@typebase` if set) | `Person` → `https://schema.org/Person` |

When you omit `@nodebase`, node ids resolve off `@document`. Since `@document` is usually a separator-less identity IRI (`…/things-fall-apart`), Onya inserts a `#` there so ids don't mash: `TFA` → `…/things-fall-apart#TFA`. That's a silent serialization rule (`LiterateParser(warn_implicit_doc_ids=True)` surfaces it). If your ontology wants ids minted under a clean path base instead (`…/classics/TFA`), set `@nodebase` explicitly with a trailing separator — choose per the IRI scheme your consumers expect.

### Properties, edges, types

- **Property**: `* label: string value` — values are **always strings** at the core layer; there are no native numbers/dates/booleans. Write `age: 28` and it's the string `"28"`.
- **Edge**: `* label -> TargetNodeID` — the target must be (or become) a `# TargetNodeID` block. Reuse the same id to refer to the same node; don't duplicate a person/place under two ids.
- **Type**: the `[Type]` in a header is optional but strongly encouraged. A node's types are a **set**, written whitespace-separated inside the brackets: `# Coyote [Organization lv:Client]` gives the node *both* types. Prefer the single most specific type when one clearly subsumes the others; use multiple when a node genuinely wears two independent hats (e.g. a schema.org class plus a project-ontology class). If a type merely specializes another (a "Client" that is a kind of `Organization`), you can instead give just the specific type and declare the hierarchy **once** in your vocabulary (a `lv:Client` node with `<rdfs:subClassOf> -> schema:Organization`) — either is valid; choose per what your consumers expect. A node can be referenced before it's defined; define each referenced node somewhere in the file.

### CURIEs and multiple vocabularies

`@schema` covers one vocabulary. For a second (e.g. a project ontology alongside schema.org), declare prefixes under `@iri`, then use `prefix:Local` for types and `<prefix:local>` for labels:

```
* @iri:
    * acme: https://acme.example.com/kg/schema

# Coyote [<acme:Client>]
* name: Coyote Corporation
* <acme:contactPoint> -> acme-cp-main
```

Bare names still resolve against `@schema`. The `schema` prefix is auto-registered from `@schema` — don't redeclare it under `@iri` with a conflicting value (parse error `SchemaPrefixConflict`). **CURIE** expansion under `@iri` follows RDF/XML namespace joining: Onya inserts a `/` separator unless the prefix base already ends in `/`, `#`, or `?`, so write `@iri` prefix bases **without** a trailing slash unless their IRIs genuinely end in one. (Bare-name `@schema`/`@nodebase` resolution is different — pure concatenation, so those bases *must* carry their own trailing separator; see Common pitfalls.) Note this means the same `@schema` base joins differently for a bare `Client` (concatenation) vs a `schema:Client` CURIE (separator-inserted); with the usual trailing-slash schema.org base both agree. Fully explicit IRIs also work: `* <https://schema.org/name>: Chinua Achebe`.

### Nested (recursive) assertions — metadata, qualified values, n-ary

Indent a list item under another to attach it to that assertion rather than the node (the examples use a 2-space indent):

```
# Boston [City]
* name: Boston
  * stateCode: "MA"          <!-- property OF the name assertion -->
  * country -> USA

* temperature: "25"          <!-- qualified value -->
  * unit: Celsius
  * measurementMethod -> InfraredThermometer
```

Edges nest the same way — put `startDate`/`role` under an edge to describe the *relationship*, which is cleaner than inventing a separate node for it. This is Onya's reification: prefer a nested assertion on the edge over a fake intermediate node, unless the relationship is genuinely a first-class entity others will link to.

### Assertion identifiers (`@id`) — making an assertion addressable

By default an assertion is **anonymous** — its identity is just its shape (origin, label, value/target). Give one an explicit identifier with a nested `* @id:` directive and it becomes a first-class, referenceable thing: another edge can point *at the assertion itself*. This is how you say something *about a specific claim* (disputes, provenance, confidence) without inventing a scaffold node.

```
# Chuks [Person]
* knows -> Ify
  * @id: chuks-knows-ify       <!-- names THIS edge; resolved against @nodebase, like a node id -->
  * since: "2018"

# Dispute [<schema:Thing>]
* about -> chuks-knows-ify     <!-- edge target is the assertion above, not a new node -->
```

`@id` is a directive, not a property (it names its enclosing assertion; it does not add a `@id` property). Identifiers **share the node id space** — an `@id` must not collide with a node id or another assertion's `@id` (a duplicate within one document raises `AssertionIdConflict`). References resolve regardless of order, so you can point at an `@id` defined later in the file. Reach for `@id` only when a claim is genuinely referenced; most reification stays anonymous nested assertions.

### Data contracts: interpretations (`@as`)

Values are always strings, but you can **record how a value is meant to be read** — a number, a date, a boolean — without changing the stored string. This is a *data contract*: honored by consumers on demand, never enforced at parse time, and it never mutates or rejects the value.

```
# Chuks [Person]
* height: 1.85
  * @as: number                <!-- records the interpretation on this property -->
* active: true
  * @as: boolean
```

Or declare defaults once in the docheader with an `@interpretations:` stanza (note the trailing colon, like `@iri:`), mapping labels to interpretations — each matching property is tagged automatically:

```
* @interpretations:
    * age: number
    * birthDate: datetime
```

Reserved interpretation names are `number`, `datetime`, `boolean`, `iri`, `text` (these resolve into the Onya interpretation vocabulary); `none` cancels a docheader default on one property; anything else is treated as an IRI (absolute IRIs and `@iri` CURIEs work). An **unknown interpretation is not an error** — the IRI simply travels with the data. Precedence: an inline `@as` overrides a docheader default overrides nothing. `@as` on an edge is ignored with a warning (an edge target is a node, not a string). Use `text` to positively assert prose (so `0042` is not "helpfully" read as a number downstream).

### Long text

A single-line value can be arbitrarily long — just write it after the `:` (quote it if it contains characters that need protecting). For **multi-line** prose, use a **text reference** (`::`): the property names a reference, and the reference is defined anywhere in the file with a triple-quoted block.

```
* bio:: achebe-bio

:achebe-bio = """Chinua Achebe (1930–2013) was a Nigerian writer…

Triple-quoted content preserves whitespace and newlines exactly, across paragraphs."""
```

The stored value is the *inner* content (the `"""` delimiters are stripped). A reference name must start with a letter, and may be reused by several properties. (There is no bare indented-continuation form — a value that spans lines must go through a `::` reference. `write()` emits multi-line values this way automatically, so they round-trip.)

### Comments

HTML comments `<!-- … -->` are ignored by the parser (and by Markdown renderers).

## Workflow: extracting a graph from a document

1. **Pick the vocabulary first.** Default to [schema.org](https://schema.org/) (`@schema: https://schema.org/`) — it has types like `Person`, `Organization`, `Book`, `City`, `Event`, `CreativeWork`, and rich property names. Reach for a custom `@iri` vocabulary only for domain concepts schema.org lacks.
2. **Set the docheader.** Choose a real, stable `@document` IRI and a `@nodebase`. Use readable, slug-style node ids (`CAchebe`, `acme-cp-main`), not opaque numbers.
3. **One block per distinct entity.** Give each a type. Pull entities (people, orgs, places, works, events) into nodes; pull their attributes into properties; pull relationships into edges to other nodes.
4. **Normalize references.** If two mentions are the same thing, use one node id for both. Make edge targets actual nodes you define.
5. **Use nesting for relationship/value metadata**, not parallel scaffolding nodes.
6. **Quote ambiguous scalars** — ISBNs, dates, codes, anything with leading zeros or special characters.
7. **Validate by parsing** (below) before reporting done.

Keep the graph faithful to the source: don't invent facts to fill out a type's expected properties. If the document doesn't state a birthDate, leave it out.

## Validate by parsing

A `.onya` file is only "done" once it parses cleanly. Round-trip it:

```bash
# Fastest check: convert is a full parse; errors surface as exceptions.
onya convert path/to/file.onya --mermaid > /dev/null
```

Or in Python for a structural check / node count:

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser

g = graph()
result = LiterateParser().parse(open('file.onya').read(), g)
print(result.doc_iri, len(g), 'nodes')
```

Watch for: dangling edge targets (an edge to an id with no block), `SchemaPrefixConflict`, `NamespaceBaseError` / a separator-less-base `DeprecationWarning`, `AssertionIdConflict` (a duplicate `@id`, or an `@id` colliding with a node id), `InterpretationParseError` (two `@as` on one property, or a repeated label in an `@interpretations` stanza), `EdgeArrowError` (a stray edge arrow — only `->` and `→` U+2192 are valid; `➡`/`⇒`/`=>`/`-->` etc. are flagged with the corrected line; parse with `lenient_arrows=True` / `onya convert --lenient_arrows` to accept-and-warn instead), `LiterateSyntaxError` (other structural slips, each with an actionable message: a spaced node id like `# Capt. Doran` → use `CaptDoran`, an unclosed `[Type]` bracket, an assertion outside a node block, or a Markdown code fence / preamble prose wrapping the graph), missing `@document`, and bare values that should have been quoted. An unknown `@as` interpretation name is **not** an error. Fix and re-parse.

## Visualize / export

The CLI (`fire`-based; flags use `--`) parses Onya Literate and emits a diagram. Multiple inputs (glob/dir/`-` for stdin) merge into one graph.

```bash
onya convert file.onya                     # Mermaid (default) → stdout; paste into https://mermaid.live/
onya convert file.onya --dot --out g.dot   # Graphviz DOT
onya convert 'dir/*.onya' --dot > all.dot  # merge several files
cat file.onya | onya convert - --mermaid   # stdin
```

Useful display flags: `--rankdir LR`, `--noshow_properties`, `--noshow_types`, `--noshow_edge_labels`, `--noshow_edge_annotations` (negate any boolean with the `no` prefix). See `demo/mermaid_basic/` and `demo/graphviz_basic/`.

For graph **analytics** (not diagrams), `onya.serial.nx` (extras-gated: `pip install "onya[nx]"`) projects a graph into a `networkx.MultiDiGraph` via `to_networkx`, and `write_back` records analytics results (centrality, communities, …) back as typed, merge-safe assertions. See `demo/nx_analytics/`.

## Merging graphs & identity

Onya has a precise notion of when two assertions are "the same", which matters whenever graphs combine — parsing several documents into one graph, unioning two graphs, or persisting into a store that already holds a graph. Parsing **never merges on its own**: overlapping assertions accumulate as distinct occurrences until a consumer explicitly calls `graph.merge()` (or `graph.union(other)`). The rules that then apply:

- **Anonymous assertions with the same *skeleton* merge** (Rule 2). A skeleton is `(origin, label, value/target)`, recursively through origins — *not* including `@id`, `interp`, or nested assertions. So two extractions of `* knows -> Ify` collapse into one edge, and their nested assertions are **unioned** onto it. Different value/target ⇒ different skeleton ⇒ they stay distinct (`nickname: Chuk` and `nickname: CK` are two claims).
- **Assertions sharing an `@id` are the same assertion** (Rule 1) and their skeletons must agree; a mismatch is a merge error.
- **An identified assertion never merges with an anonymous one** (Rule 3), even with an identical skeleton — the `@id` marks a deliberately distinct, addressable occurrence.
- **Interpretations ride along**: equal-or-one-absent `interp` merges (the present one is adopted); two *different* non-absent interps on the same anonymous skeleton stay distinct (two parties making different contracts about the same words — not an error); a differing interp on same-`@id` assertions is an error.

Authoring implications: to make two documents' claims **coalesce**, give the shared entities the **same node ids** and write structurally identical assertions. To keep a claim **separate and referenceable**, give it an `@id`. Don't rely on merge to dedupe things you spelled differently — normalize ids and values yourself.

## Persistence — storing graphs with `onya.store`

Authoring produces `.onya` files, which are themselves durable and diffable — often all you need. When a **downstream Python project** needs to accumulate graphs across sessions/processes, query without loading everything, or use a real database, the `onya.store` layer offers three backends behind one async protocol, chosen by URL scheme:

```python
from onya.store import connect
from onya.serial.literate import read

r = read(open('classics/things-fall-apart.onya'))

async def save():
    # file: (one .onya file per graph — the default, doubles as the testing fake)
    # sqlite: (stdlib, zero extra deps) | postgresql:// (pip install "onya[postgres]")
    async with await connect('sqlite:kb.db') as store:
        await store.put(r.doc_iri, r.graph)      # merge=True: unions with any stored graph
        again = await store.get(r.doc_iri)
```

The load-bearing guarantee: **a round trip through a store is identical to an in-memory graph union** — `put(merge=True)` applies exactly the merge rules above, so the same-ids/skeletons discipline from authoring is what controls how stored graphs combine. A blocking facade (`from onya.store.sync import connect`) mirrors the API for scripts. Backends, schema, and the SQL/PGQ layer are documented in [doc/design-persistence-architecture.md](https://github.com/OoriData/Onya/blob/main/doc/design-persistence-architecture.md); the walkthrough is in [doc/python-tutorial.md](https://github.com/OoriData/Onya/blob/main/doc/python-tutorial.md). The store emits `.onya` and reads `.onya`/`.onya.md`.

## Common pitfalls

- **Multi-type headers are fine, but don't over-stack.** `[Organization lv:Client]` parses as a *set* of two types (as of 0.4.0; older Onya rejected it). That's correct when a node genuinely has two independent types — but if one merely specializes the other, prefer the single specific type and model "is-a-kind-of" as a vocabulary `rdfs:subClassOf`, rather than stacking both on every instance.
- **`@nodebase` / `@schema` / `@typebase` must end in a separator (`/`, `#`, or `?`).** Node ids and bare labels/types are joined by **pure concatenation**, so `@nodebase: https://ex.org/g` yields `https://ex.org/gMyNode` (mashed), not `…/g/MyNode`. End these bases with `/`. As of 0.3.1 the parser warns on a separator-less base and `LiterateParser(strict_namespace_bases=True)` raises `NamespaceBaseError` (strict becomes the default in a future release). (This differs from `@iri` CURIE prefixes, which *do* get RDF/XML separator insertion — see below.)
- **Trailing slash on an `@iri` CURIE base.** CURIEs (`prefix:Local`, `<prefix:local>`) expand by RDF/XML rules: Onya inserts a `/` only when the base lacks a trailing `/`, `#`, or `?`. So write `@iri` prefix bases **without** a trailing slash unless the vocabulary IRIs genuinely end in one — `acme: https://acme.example/kg/schema` with `acme:Client` yields `…/schema/Client`. (Contrast the bullet above: bare names against `@schema`/`@nodebase` are *not* separator-inserted, so those bases must carry their own trailing separator.)
- **Confusing `@nodebase` and `@schema`.** Node ids resolve against `@nodebase`; labels and types against `@schema`. They are different bases.
- **Treating values as typed.** Everything is a string. Don't expect `age: 28` to be a number; if order/typing matters, that's a layer above the core model.
- **Inventing a node for every relationship.** Reify with a nested assertion on the edge instead, unless the relationship is a real entity.
- **Unquoted special values.** Leading-zero ISBNs, `YYYY-MM` dates, codes → quote them.
- **Forgetting to define an edge target.** Every `-> Foo` needs a `# Foo` block.

## If the task is unclear

Ask: which vocabulary/ontology (schema.org vs. a project-specific one)? what `@document`/`@nodebase` IRIs to use? and is the output a single file or a merged set? Default to schema.org + a single file when unspecified.
