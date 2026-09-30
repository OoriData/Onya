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

**Inline form: prefer it.** `[=name]` at the end of the assertion line means exactly the same as a nested `* @id: name`, and keeps the name on the line it names:

```
# Chuks [Person]
* knows -> Ify [=chuks-knows-ify]
  * since: "2018"
* name: Chukwuemeka Okafor [=chuks-name]     <!-- works on properties too, quoted or not -->
```

The `=` is required (a bare `[name]` would read like a type bracket). Use one form or the other on a given assertion, not both (a parse error). An unquoted value that should literally end in ` [=x]` must be quoted. `write()` emits the nested `* @id:` form, which is the normative one; the two parse to identical graphs.

`@id` is a directive, not a property (it names its enclosing assertion; it does not add a `@id` property). Identifiers **share the node id space** — an `@id` must not collide with a node id or another assertion's `@id` (a duplicate within one document raises `AssertionIdConflict`). References resolve regardless of order, so you can point at an `@id` defined later in the file. Reach for `@id` when a claim is genuinely referenced, or when its nested qualifiers must stay bound together (see *Keep qualifier bundles apart* below); otherwise reification stays anonymous nested assertions.

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

A single-line value can be arbitrarily long — just write it after the `:` (quote it if it contains characters that need protecting). For **multi-line** prose, either continue the value on indented lines, as in a Markdown list item, or use a text reference.

**Indented continuation** is the more readable form. Lines indented at least 2 spaces past the bullet (4 works too) that don't start with `* ` continue the value, with or without a blank line first:

```
# CAchebe [Person]
* bio: Chinua Achebe (1930–2013) was a Nigerian writer.

    Known for Things Fall Apart, he wrote about African life from an African perspective.
  * @as: text
* birthDate: "1930-11-16"
```

The value is kept exactly: newlines and blank lines as written, and indentation relative to the continuation block. Put directives and nested assertions (`@as`, `@id`, `* note: …`) *after* the text. An inline `[=id]` or a comment stays on the first line. It works for properties with an unquoted (or empty) first line; not for edges or quoted values. Unindented text never continues a value: it's a parse error, so stray prose is caught rather than swallowed.

**A text reference** (`::`) suits content that indentation would mangle, such as text whose own lines start with `* `. The property names a reference, and the reference is defined anywhere in the file with a triple-quoted block.

```
* bio:: achebe-bio

:achebe-bio = """Chinua Achebe (1930–2013) was a Nigerian writer…

Triple-quoted content preserves whitespace and newlines exactly, across paragraphs."""
```

The stored value is the *inner* content (the `"""` delimiters are stripped). A reference name must start with a letter, and may be reused by several properties. `write()` emits multi-line values as text references by default; `write(..., multiline='indent')` uses indented continuation instead, falling back to a text reference for a value that form can't represent exactly.

### Comments

HTML comments `<!-- … -->` are ignored by the parser (and by Markdown renderers).

## Workflow: extracting a graph from a document

1. **Pick the vocabulary first.** Default to [schema.org](https://schema.org/) (`@schema: https://schema.org/`) — it has types like `Person`, `Organization`, `Book`, `City`, `Event`, `CreativeWork`, and rich property names. Reach for a custom `@iri` vocabulary only for domain concepts schema.org lacks.
2. **Set the docheader.** Choose a real, stable `@document` IRI and a `@nodebase`. Use readable, slug-style node ids (`CAchebe`, `acme-cp-main`), not opaque numbers.
3. **One block per distinct entity.** Give each a type. Pull entities (people, orgs, places, works, events) into nodes; pull their attributes into properties; pull relationships into edges to other nodes.
4. **Normalize references.** If two mentions are the same thing, use one node id for both. Make edge targets actual nodes you define.
5. **Use nesting for relationship/value metadata**, not parallel scaffolding nodes. Keep labels atomic and values clean: no years, units, kinds or sources baked into a label name, and no parenthetical asides in a value (see *Good knowledge primitives* below).
6. **Quote ambiguous scalars** — ISBNs, dates, codes, anything with leading zeros or special characters.
7. **Validate by parsing** (below) before reporting done.

Keep the graph faithful to the source: don't invent facts to fill out a type's expected properties. If the document doesn't state a birthDate, leave it out.

## Good knowledge primitives: atomic labels, clean values

Generators (LLMs especially) tend to pack qualifiers into the *label* (`ex:gdp2025`, `homePhone`) or into the *value* (`"5,000,000 (2024 est.)"`). Both hide facts where no tool can reach them. **A label names one relation; a value holds one value; every qualifier (when, where, which unit, which kind, how sure, according to whom) is its own nested assertion.** Nesting is how Onya expresses a qualified statement, so use it.

**Compound labels → base label plus nested qualifiers:**

| Instead of | Write |
|---|---|
| `ex:gdp2025: "30.5e12"` | `ex:gdp: "30.5e12"` with nested `temporalCoverage: "2025"` |
| `ex:populationFemale: …` | `ex:population: …` with nested `ex:subgroup -> ex:Female` |
| `ex:priceUSD: "12.50"` | `price: "12.50"` plus `priceCurrency: USD` (schema.org already has it) |
| `homePhone`, `workPhone` | `telephone: …` with nested `ex:use -> ex:Home` / `ex:use -> ex:Work` |
| `ex:heightCm: "180"` | `height: "180"` with nested `unitCode: CMT` |
| `ex:currentCeo -> X`, `ex:formerCeo -> Y` | `ex:ceo -> X` with nested `startDate` (and `endDate` for Y) |
| `ex:firstAuthor`, `ex:secondAuthor` | `author -> X` with nested `position: "1"` |
| `ex:estimatedRevenue` | `ex:revenue` with nested `@method` / `@confidence` (the reserved provenance vocabulary) |

**Parentheticals and asides in values → the same move.** The value is just the value; the aside is a qualifier or an entity:

| Instead of | Write |
|---|---|
| `population: "5,000,000 (2024 est.)"` | `population: "5000000"` (`@as: number`) with nested `temporalCoverage: "2024"` and `ex:status -> ex:Estimate` |
| `height: "180 cm"` | `height: "180"` with nested `unitCode: CMT` |
| `birthDate: "1815 (approx.)"` | `birthDate: "1815"` with nested `ex:precision -> ex:Approximate` |
| `email: "ada@example.org (preferred)"` | `email: ada@example.org` with nested `ex:use -> ex:Primary` |
| `honorificPrefix: "Countess (by marriage)"` | `honorificPrefix: Countess` with nested `ex:basis -> ex:Marriage` |
| `location: "Paris (France)"` | an edge to a place node: `location -> paris`, where `# paris [City]` has `containedInPlace -> france` |
| `worksFor: "Acme Corp (until 2019)"` | `worksFor -> acme` with nested `endDate: "2019"` |

A worked example:

```
# usa [Country]
* name: United States
* ex:gdp: "29.2e12"
  * @as: number
  * temporalCoverage: "2024"
  * unitCode: USD
* ex:gdp: "30.5e12"
  * @as: number
  * temporalCoverage: "2025"
  * unitCode: USD
  * ex:status -> ex:Estimate
```

**Why it matters, concretely:**

- **Queries and lookups work on the relation.** `g.select(label=EX('gdp'))` (with `EX = I('http://example.org/vocab/')`), a store's `match(label=...)`, and `g.search(labels=[...])` find every year's GDP. With `ex:gdp2019` … `ex:gdp2025` a consumer must enumerate or string-match label names: the fragile local-name matching the rest of the toolchain avoids.
- **Views can choose among values.** `{ label = "ex:gdp", as = "latest_gdp", order_by = "-temporalCoverage" }` shows the most recent figure; `prefer = { label = "ex:use", target = "ex:Primary" }` picks the primary email. A compound label or a parenthetical gives them nothing to rank by.
- **Values stay typed.** `"5000000"` with `@as: number` is a number to every consumer (`onya.interp.value_of`); `"5,000,000 (2024 est.)"` is only ever a string.
- **Vocabularies line up.** `temporalCoverage`, `priceCurrency`, `unitCode`, `startDate`, `position` already exist in schema.org, so graphs from different sources agree. A minted `ex:gdp2025` matches nothing, not even `ex:gdp2024`.

**Keep qualifier bundles apart when values can coincide.** Anonymous assertions with the same label and value *merge* (Rule 2), and their nested qualifiers union. So two sources both reporting population `"5000000"`, one for 2023 from a census bureau and one for 2024 from the UN, become one assertion carrying both years and both sources, and which year goes with which source is lost. When qualifiers must stay bound to one another, give each qualified assertion an id. An identified assertion merges only with another occurrence of the *same* id, never with an anonymous or differently-identified one (Rules 1 and 3). The inline form makes this cheap:

```
# nigeria [Country]
* ex:population: "5000000" [=nigeria-pop-2023]
  * @as: number
  * temporalCoverage: "2023"
  * ex:source -> ex:CensusBureau
* ex:population: "5000000" [=nigeria-pop-2024]
  * @as: number
  * temporalCoverage: "2024"
  * ex:source -> ex:UNData
```

Choose ids that say what the bundle is (`nigeria-pop-2024`), so a second extraction of the same fact from the same source reuses the id and merges as intended, while a different year or source never does. Alternatively, model the figure as an observation node (below).

**When a compound label is fine, and when to use a node instead:**

- **Use established terms as they are.** `birthDate`, `foundingDate` and `priceCurrency` are atomic *in their vocabulary*; don't split them into `birth` + a date qualifier. The test: would the qualifier plausibly vary across values of the same relation (different years, units, kinds, sources)? If so, it's a qualifier, not part of the label.
- **Use a node when the qualified thing is itself an entity** that others refer to, or whose qualifiers need their own qualifiers: a census release, a dataset, a statistical observation (`# usa-gdp-2025 [Observation]`). Its properties still follow the same rule: atomic labels, clean values.

## Validate by parsing

A `.onya` file is only "done" once it parses cleanly. Round-trip it:

```bash
# Fastest check: convert is a full parse; errors surface as exceptions.
onya convert path/to/file.onya --mermaid > /dev/null
```

Or in Python for a structural check / node count:

```python
from onya.graph import graph
from onya.serial.literate import read

g = graph()
result = read(open('file.onya').read(), g)   # accepts a str or a file-like; returns a ParseResult
print(result.doc_iri, len(g), 'nodes')
```

`read` and `write` are the top-level entry points (`read` is `LiterateParser().parse()` with defaults; both return a `ParseResult`). Reach for `LiterateParser(...)` directly only when you need a behavior flag — e.g. `lenient_arrows=True`, `warn_implicit_doc_ids=True`, `strict_namespace_bases=True`, `warn_empty_blocks=False`.

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

For graph **analytics** (not diagrams), `onya.viz.nx` (extras-gated: `pip install "onya[nx]"`) projects a graph into a `networkx.MultiDiGraph` via `to_networkx`, and `write_back` records analytics results (centrality, communities, …) back as typed, merge-safe assertions. See `demo/nx_analytics/`.

## Serialize a graph back to authoring form (`write`)

`read` and `write` are inverses — `read(write(g))` equals `g` — which is what makes the "materialize a graph → serialize → commit to git → re-seed" workflow safe. Two things to know when *exporting* a graph (as opposed to authoring by hand):

- **Faithful under any namespace choice, but bases must be separator-terminated.** `write` only compacts an IRI to a bare/CURIE name when it genuinely lives under a declared base; everything else is emitted as an explicit `<full-iri>`. The one precondition is that `@schema`/`@nodebase` end in `/`, `#`, or `?` — bare names join by concatenation, so a separator-less base would mash on reparse (`…/vocab` + `title` → `…/vocabtitle`). `write` enforces this: it normalizes a separator-less base (appending `/`) and warns, or raises `NamespaceBaseError` under `write(..., strict_namespace_bases=True)`. So: **always pass separator-terminated bases.**
- **A graph only partly remembers its authoring convention**: its data holds full IRIs; `g.prefixes` keeps the parsed prefix map (non-canonical, for CURIE-keyed access), but not `@nodebase`, and `write()` doesn't consult it on its own. `write(g, document=…)` with no other hints round-trips *correctly* but verbosely — every name becomes `<https://schema.org/name>`. To reproduce the compact authored form (bare `name`, `lv:score`), pass the namespaces back: `read` hands them to you on `ParseResult` (`r.schema`, `r.nodebase`, `r.typebase`, `r.prefixes`), so `write(g, document=r.doc_iri, schema=r.schema, nodebase=r.nodebase, prefixes=r.prefixes)` re-emits in the original style. Don't try to guess the convention — thread the real one. (The `onya.store` filesystem backend does this automatically: `put(merge=True)` preserves a seeded file's convention across round trips, and writes a new graph with its own `g.prefixes`. All stores return graphs carrying the prefixes they were `put` with.)

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

## Looking up nodes from application code

Downstream code shouldn't hand-roll "find the node the user named" or reverse-edge scans, and shouldn't compare IRI tails ("local names") — `schema:name` and `ex:name` collide that way. Instead:

- **Prefer full IRIs in application code.** Define namespace constants once and build labels from them — `SCHEMA = I('https://schema.org/')`, then `SCHEMA('name')`, `SCHEMA('Person')` — and pass those `I` values to accessors, `search`, and store calls. A full IRI means the same thing against every graph; a CURIE or bare name means whatever *this* graph's docheader happened to bind (prefixes are non-canonical), so it breaks or silently changes meaning on a graph from another source, one with a clashing merge, or a store written before prefixes were kept. `I` values also skip resolution entirely (the fast path). Store `search`/`match` take full IRIs only, deliberately.
- **CURIEs are for authoring and for data tied to one vocabulary convention**: `.onya` files themselves, view specs kept beside the documents they describe, REPL exploration. A parsed graph keeps its docheader prefixes as `g.prefixes`, and label arguments to `getprop`/`getedge`/`any_prop_value`/`any_edge_target`/`select`/`typematch`/`inbound`/`search` accept a full IRI, a CURIE (`'schema:name'`), or a bare `@schema` name (`'name'`). An undeclared prefix raises `UnknownPrefixError` rather than guessing.
- **Ranked search.** `g.search('ada lovelac', labels=[SCHEMA('name')], types=[SCHEMA('Person')], limit=5)` → `list[SearchHit]` (`node_id`, `node`, `label`, `value`, `tier`, `score`). Tiers: `exact` > `prefix` (word-boundary) > `word` > `fuzzy`; tier beats score. Default labels: properties with no `@as` or `@as: text`. It never picks for you — `hits[0]` plus `SearchHit.is_clear_winner(hits)` is the usual pattern. `similarity='rapidfuzz'` (needs `onya[fuzzy]`) is a faster opt-in scorer. Keep a reference to the graph while using its nodes' CURIE accessors — nodes hold their graph only weakly.
- **Inbound edges.** `g.inbound(node_or_id, label=None)` (index-backed; `node.reverse(label, g)` wraps it).
- **Showing a node.** Avoid hand-writing per-type renderers; instead declare a view: `view.project(g, node, view.load(toml_data))` with specs like `{type='schema:Person', fields=['name', {label='email', many=true}], follow=[{edge='worksFor', as='employer', show=['name'], edge_props=['startDate']}, {inbound='author', as='works', show=['name'], order_by='-datePublished', limit=10}]}`. Output is ordered plain data (`title`, then `fields` as `(name, value)` pairs); missing data is omitted, never an error. `many=false` shows one value: the least, unless the field ranks its values with `prefer` (patterns over each value's own nested assertions: `prefer={label='ex:use', target='ex:Primary'}`, `{label='ex:primary', value=true}`, or a list tried in order) and/or `order_by='ex:priority'` (a nested value, typed via `@as`). Follows take `prefer` too, matched against the link's own nested assertions, e.g. `prefer={label='ex:current', value=true}, limit=1`. In specs, `label` always means an assertion label; the display string is `title=` (the old view-level `label=` still works but is deprecated until 0.6.0). `view.project_from_store(store, name, node_id, specs)` fetches only the needed neighborhood.
- **In a store.** `await store.search(name, query, labels=[full IRIs], ...)` and `store.nodes_by_type(name, type_iri)` work on every backend without loading the graph (PostgreSQL uses a `pg_trgm` index; its fuzzy scores are trigram-based, so fuzzy hits near `min_score` can differ from other backends — tiers and non-fuzzy hits don't). Store arguments are full IRIs — a store has no prefix map.

## Common pitfalls

- **Multi-type headers are fine, but don't over-stack.** `[Organization lv:Client]` parses as a *set* of two types (as of 0.4.0; older Onya rejected it). That's correct when a node genuinely has two independent types — but if one merely specializes the other, prefer the single specific type and model "is-a-kind-of" as a vocabulary `rdfs:subClassOf`, rather than stacking both on every instance.
- **`@nodebase` / `@schema` / `@typebase` must end in a separator (`/`, `#`, or `?`).** Node ids and bare labels/types are joined by **pure concatenation**, so `@nodebase: https://ex.org/g` yields `https://ex.org/gMyNode` (mashed), not `…/g/MyNode`. End these bases with `/`. As of 0.3.1 the parser warns on a separator-less base and `LiterateParser(strict_namespace_bases=True)` raises `NamespaceBaseError` (strict becomes the default in a future release). (This differs from `@iri` CURIE prefixes, which *do* get RDF/XML separator insertion — see below.)
- **Trailing slash on an `@iri` CURIE base.** CURIEs (`prefix:Local`, `<prefix:local>`) expand by RDF/XML rules: Onya inserts a `/` only when the base lacks a trailing `/`, `#`, or `?`. So write `@iri` prefix bases **without** a trailing slash unless the vocabulary IRIs genuinely end in one — `acme: https://acme.example/kg/schema` with `acme:Client` yields `…/schema/Client`. (Contrast the bullet above: bare names against `@schema`/`@nodebase` are *not* separator-inserted, so those bases must carry their own trailing separator.)
- **Confusing `@nodebase` and `@schema`.** Node ids resolve against `@nodebase`; labels and types against `@schema`. They are different bases.
- **Treating values as typed.** Everything is a string. Don't expect `age: 28` to be a number; if order/typing matters, that's a layer above the core model.
- **Compound labels and parenthetical values.** `ex:gdp2025`, `homePhone`, `"180 cm"`, `"1815 (approx.)"`: split into a base label or clean value plus nested qualifiers (see *Good knowledge primitives*).
- **Inventing a node for every relationship.** Reify with a nested assertion on the edge instead, unless the relationship is a real entity.
- **Tab characters.** Don't emit tabs in Onya Literate: indent with spaces (2 or 4 per level), and if a value genuinely contains a tab, write it as `\t` inside a quoted value (`* d: "col1\tcol2"`). The parser does handle tabs the Markdown way (a tab in leading indentation counts to the next multiple of 4 columns; a tab inside a value is kept as a tab), but tabs are invisible in review, render differently across editors, and mixing them with spaces makes nesting hard to see.
- **Unquoted special values.** Leading-zero ISBNs, `YYYY-MM` dates, codes → quote them.
- **Forgetting to define an edge target.** Every `-> Foo` needs a `# Foo` block.

## If the task is unclear

Ask: which vocabulary/ontology (schema.org vs. a project-specific one)? what `@document`/`@nodebase` IRIs to use? and is the output a single file or a merged set? Default to schema.org + a single file when unspecified.
