---
name: onya-graph
description: Author Onya knowledge graphs in the Onya Literate (.onya.md) Markdown format — docheader, node blocks, properties, edges, types, CURIEs, nested/reified assertions, long text, validation by parsing, and Mermaid/Graphviz export. Use when creating, editing, extracting, or reviewing Onya graphs (e.g. turning a document into a .onya knowledgebase, or hand-writing/fixing one).
---

# Authoring Onya Graphs

## Purpose

Onya is a knowledge-graph model — nodes, edges, properties, all identified by IRIs — with a human-friendly Markdown serialization called **Onya Literate**. Prefer the **`.onya.md`** extension: it is Markdown, so Markdown-aware tools (GitHub, editors, diff viewers) render and fold it correctly with no Onya support, while a bare `.onya` shows as plain text. This skill is how to author, fix, and validate these files, including the common task of extracting a knowledge graph from a source document.

The model is deliberately tiny: a **node** has an id (IRI), a set of types, and a set of assertions; an **assertion** is either a **property** (label IRI → string value) or an **edge** (label IRI → target node). Assertions are themselves anonymous nodes, so **any assertion can carry its own nested assertions** — that is how Onya does relationship metadata, qualified values, and n-ary relations without extra machinery. Authoritative reference: [the Onya Model Specification](https://github.com/OoriData/Onya/blob/main/SPEC.md). Treat the code and spec as source of truth over this summary.

## When to use / not use

- **Use** when the deliverable is a `.onya` file: extracting a KG from prose, hand-authoring one, or repairing/reviewing an existing graph.
- **Not** for the Python graph API itself (`onya.graph`, `LiterateParser`, traversal) — that's library work; see the README example and `pylib/`. This skill covers the *authoring* surface and uses the parser only to validate.

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
- **Type**: the `[Type]` in a header is optional but strongly encouraged. **Give a node exactly one type — the most specific one.** Onya Literate headers take a single type today; multiple space-separated types (`[Organization lv:Client]`) currently fail to parse. When your domain type specializes a schema.org class (e.g. a "Client" that is a kind of `Organization`), do **not** stack both on the node — pick the specific one (`[<lv:Client>]`) and, if the hierarchy matters to consumers, declare the relationship **once** in your vocabulary: a `lv:Client` node with an edge `<rdfs:subClassOf> -> schema:Organization`. A node can be referenced before it's defined; define each referenced node somewhere in the file.

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

### Long text

Two options for prose-length values:

```
* bio: Chinua Achebe (1930–2013) was a Nigerian writer…

    Continuation paragraphs are indented 4+ spaces after a blank line; newlines are preserved.
```

Or a **text reference** (`::`), definable anywhere in the file, good for reuse or keeping long blocks out of the structure:

```
* bio:: achebe-bio

:achebe-bio = """Chinua Achebe (1930–2013) was a Nigerian writer…
Triple-quoted content preserves whitespace and newlines exactly."""
```

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

Watch for: dangling edge targets (an edge to an id with no block), `SchemaPrefixConflict`, `NamespaceBaseError` / a separator-less-base `DeprecationWarning`, missing `@document`, and bare values that should have been quoted. Fix and re-parse.

## Visualize / export

The CLI (`fire`-based; flags use `--`) parses Onya Literate and emits a diagram. Multiple inputs (glob/dir/`-` for stdin) merge into one graph.

```bash
onya convert file.onya                     # Mermaid (default) → stdout; paste into https://mermaid.live/
onya convert file.onya --dot --out g.dot   # Graphviz DOT
onya convert 'dir/*.onya' --dot > all.dot  # merge several files
cat file.onya | onya convert - --mermaid   # stdin
```

Useful display flags: `--rankdir LR`, `--noshow_properties`, `--noshow_types`, `--noshow_edge_labels`, `--noshow_edge_annotations` (negate any boolean with the `no` prefix). See `demo/mermaid_basic/` and `demo/graphviz_basic/`.

## Common pitfalls

- **One type per node header.** `[Organization lv:Client]` (or any multi-type header) does not parse — the bracket is read as a single IRI and the space makes it invalid. Use one specific type; model "is-a-kind-of" as a vocabulary `rdfs:subClassOf`, not a second header type.
- **`@nodebase` / `@schema` / `@typebase` must end in a separator (`/`, `#`, or `?`).** Node ids and bare labels/types are joined by **pure concatenation**, so `@nodebase: https://ex.org/g` yields `https://ex.org/gMyNode` (mashed), not `…/g/MyNode`. End these bases with `/`. As of 0.3.1 the parser warns on a separator-less base and `LiterateParser(strict_namespace_bases=True)` raises `NamespaceBaseError` (strict becomes the default in a future release). (This differs from `@iri` CURIE prefixes, which *do* get RDF/XML separator insertion — see below.)
- **Trailing slash on an `@iri` CURIE base.** CURIEs (`prefix:Local`, `<prefix:local>`) expand by RDF/XML rules: Onya inserts a `/` only when the base lacks a trailing `/`, `#`, or `?`. So write `@iri` prefix bases **without** a trailing slash unless the vocabulary IRIs genuinely end in one — `acme: https://acme.example/kg/schema` with `acme:Client` yields `…/schema/Client`. (Contrast the bullet above: bare names against `@schema`/`@nodebase` are *not* separator-inserted, so those bases must carry their own trailing separator.)
- **Confusing `@nodebase` and `@schema`.** Node ids resolve against `@nodebase`; labels and types against `@schema`. They are different bases.
- **Treating values as typed.** Everything is a string. Don't expect `age: 28` to be a number; if order/typing matters, that's a layer above the core model.
- **Inventing a node for every relationship.** Reify with a nested assertion on the edge instead, unless the relationship is a real entity.
- **Unquoted special values.** Leading-zero ISBNs, `YYYY-MM` dates, codes → quote them.
- **Forgetting to define an edge target.** Every `-> Foo` needs a `# Foo` block.

## If the task is unclear

Ask: which vocabulary/ontology (schema.org vs. a project-specific one)? what `@document`/`@nodebase` IRIs to use? and is the output a single file or a merged set? Default to schema.org + a single file when unspecified.
