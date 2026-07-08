Onya Model Specification

# Overview

Onya is a knowledge graph framework with a simple, recursive model for representing structured information. The core model is intentionally minimal—just nodes, edges, and properties, identifiable by IRIs.

# Core Concepts

## Graph

Collection of nodes managed together. Provides the top-level container for the Onya model.

## Node

Fundamental unit of information in Onya. Each node has:

- **id**: An identifier expressed as an IRI
- **types**: A set of IRIs that classify the node
- **assertions**: A set of edges and properties

Nodes use **sets** (not sequences) for assertions because pervasive ordering is not a core requirement of the model. Other layers can add ordering as needed.

## Assertions

Edges and properties are collectively called **assertions**. Like a node, an assertion is an instance that can carry its own nested assertions; unlike a node, it is **anonymous by default**, carrying no externally addressable name. Each assertion is distinguished by the combination of:
- its origin (a node or another assertion)
- its label (an IRI)
- its target node (edge) or string value (property)
- an internal marker that differentiates it from otherwise-identical assertions

An assertion MAY be given an explicit identifier, making it addressable in the same identifier space as node IDs — see [Assertion Identifiers](#assertion-identifiers).

### Edge

An **edge** connects an origin to a target node via an IRI label.

```
origin --[IRI label]--> target node
```

### Property

A **property** connects an origin to a string value via an IRI label.

```
origin --[IRI label]--> "string value"
```

### Literate syntax

The above text ilustrations are pseudocode, but not terribly far from the human **and** machine readable **and** editable Onya Literate syntax.

Here is a snippet from a simple friendship graph, describing an entity identified as `Chuks`:

```
# Chuks [Person]

* name: Chukwuemeka Okafor
* knows -> Ify
  * startDate: 2018-03-15
```

`Chuks`, `Person`, `name`, `Ify`, and `startDate` would all be resolved as full IRIs.

The Unicode arrow `→` (U+2192) is accepted as a synonym for `->`.

```
# Chuks [Person]

* name: Chukwuemeka Okafor
* knows → Ify
  * startDate: 2018-03-15
```

`Person` is the type asserted for `Chuks`. `name` is a property, so `Chukwuemeka Okafor` is a string, not another entity. `knows` is an edge, so `Ify` is another entity, not defined in this snippet. `startDate` is a property of the `knows` edge.

## Assertion Identifiers

Assertions are **anonymous by default**. Each assertion is an instance,
distinguished internally from otherwise-identical assertions, but carrying
no externally addressable name.

An assertion MAY be given an explicit identifier, making it addressable:

- The identifier is an IRI, occupying the same identifier space as node IDs.
- An identifier is unique within the graph: it MUST NOT collide with a node
  ID or with another assertion's identifier.
- An identified assertion may appear as the **target of an edge**, exactly
  as a node would. (Assertions, identified or not, are never edge *labels*.)
- An assertion has at most one identifier.

### Literate syntax

In Onya Literate, the identifier is declared with the built-in `@id`
directive as a nested line, resolved against `@nodebase` like any node ID:

```
# Chuks [Person]

* knows -> Ify
  * @id: chuks-ify-friendship
  * startDate: 2018-03-15
```

`@id` is a directive, not an assertion: it names the edge or property, and
does not create a property on it. Once named, the assertion is a valid edge
target:

```
# ReviewNote

* disputes -> chuks-ify-friendship
  * source -> InterviewTranscript03
```

`@id` resolves into the same space as node IDs. It is a
parse-time error for an `@id` to collide with a node ID, or with another assertion's `@id`.

### Identity and graph merge

An assertion's **skeleton** is the triple of (origin, label, target) for an
edge, or (origin, label, value) for a property. The skeleton excludes nested
assertions and excludes the identifier itself: annotating an assertion never
changes its identity.

Under graph union:

1. Two assertions bearing the same identifier are the same assertion. Their
   skeletons MUST match; a mismatch is a merge error. Their nested
   assertions are unioned, recursively under these same rules.
2. Two anonymous assertions with equal skeletons merge into one; their
   nested assertions are unioned, recursively. (Origins compare under the
   merge: nested assertions whose parents have merged share an origin.)
3. An identified assertion never merges with an anonymous one, even when
   skeletons match. An explicit identifier is a declaration that this
   occurrence is distinct.

Rule 2 gives Onya idempotent merge ergonomics by default, desirable behavior when combining graphs extracted from overlapping sources.
Rules 1 and 3 preserve occurrence semantics exactly where a modeler has declared they matter. Implementations MAY offer alternative merge policies (e.g., absorbing a structurally equal anonymous assertion into an identified one), but the rules above are the normative default.

# Example: assertions in practice

The pieces above — anonymous assertions that can themselves carry assertions, made addressable only when a modeler chooses — cover a surprising range of modeling needs with no extra machinery. A small scenario shows how they fit together.

A mother can have multiple children. In Onya, each parental relationship can be modeled with an edge from the node representing the mother (the assertion's origin) to the node representing the child (the assertion's target). Each of these edges is a separate assertion (anonymous by default) which can have its own assertions, e.g. date of labor (though of course another modeler could choose to model this instead just using a date of birth edge on each child node).

Because those edges are anonymous, the identity rules above apply automatically: the same parental edge extracted independently from two overlapping sources merges into one when their skeletons match (Rule 2), so combining graphs is idempotent without any bookkeeping. Where a modeler instead needs to hold two structurally identical assertions apart as genuinely distinct occurrences, giving each an `@id` declares that intent and preserves the distinction through merge (Rule 3).

# Notes

## String Properties

Properties in Onya always have string values. There are no numbers, dates, or other types at the core layer. Annotation systems can be built on top to add typing semantics.

## Recursive Structure

A key feature of Onya is that **assertions themselves can be origins for further assertions**. This natural recursiveness means:

- An edge can have properties and edges
- A property can have properties and edges
- There's no separate concept of "attributes" - just recursive assertions

This enables representation of:
- Metadata about relationships (e.g., a marriage with a date and location)
- Qualified values (e.g., a temperature with units and measurement method)
- N-ary relationships (e.g., a sale with buyer, seller, item, and price)

## IRIs Throughout

All identifiers in Onya are IRIs:
- Node IDs
- Node types
- Edge labels
- Property labels

This provides a uniform, standard way to identify and dereference all elements of the graph.

# Onya Literate Serialization

The human-friendly Onya Literate format is based on Markdown, making it easy to read and write knowledge graphs.

### File Structure

An Onya Literate file contains:

1. **Document Header** - metadata about the document itself
2. **Node Blocks** - definitions of nodes and their assertions

## Comments

Comments use HTML comment syntax:

```
<!-- This is a comment -->
```

These are ignored by the parser and do not appear in the graph in any way. They will also be ignored by most markdown processors.

## Document Header

```
# @docheader

* @document: http://example.org/doc
* title: Example Document
* @nodebase: http://example.org/
* @schema: https://schema.org/
* @language: en
* @iri:
    * acme: https://acme.example.com/kg/schema
    * schema: https://schema.org
```

The document header specifies:
- `@document`: IRI of the document itself (required)
- `@nodebase`: Base IRI for resolving relative node IDs, whether as origins or edge targets; if omitted, `@document` is used as the node base (with a `#` inserted as the separator when `@document` lacks a trailing `/`, `#`, or `?`)
- `@schema`: Base IRI for schema vocabulary—used to expand both property/edge labels AND types (required in nearly all cases)
- `@typebase`: Base IRI for resolving relative type IRIs; only needed in less common cases where types use a different base than properties. If omitted, types use `@schema` as the base.
- `@language`: Default language for string values
- `@iri`: Optional block declaring extra vocabulary namespace bases (see below)
- Other assertions are attached to the document node

**Important**: The `@nodebase` directive is used exclusively for expanding node IDs (e.g., `Chuks` → `http://example.org/people/Chuks`). The `@schema` directive is used for expanding both property labels (e.g., `name` → `https://schema.org/name`) and types (e.g., `[Person]` → `https://schema.org/Person`). It should be extremely unusual for an Onya file not to have a `@schema` directive.

**Bare-name bases must end in a separator.** Node ids join to `@nodebase`, and bare property/edge labels and types join to `@schema`/`@typebase`, by **pure concatenation** — no separator is inserted. So these bases must end in `/`, `#`, or `?`, or they mint mashed IRIs (`@nodebase https://ex.org/g` + `Node` → `https://ex.org/gNode`). As of 0.3.1 the parser warns on a separator-less explicit `@nodebase`/`@schema`/`@typebase` (`DeprecationWarning`), and `LiterateParser(strict_namespace_bases=True)` rejects it with `NamespaceBaseError`; a future release will make strict the default. This is *not* the same as `@iri` CURIE joining, which does insert a separator — see below.

**The `@nodebase`→`@document` fallback is the exception.** When `@nodebase` is omitted, node ids resolve off `@document`, which is an identity IRI and conventionally has no trailing separator (e.g. `…/things-fall-apart`). Rather than mash, Onya inserts a `#` here as an implicit separator, so `@document …/things-fall-apart` + `TFA` → `…/things-fall-apart#TFA`. This is a silent serialization rule; build the parser with `LiterateParser(warn_implicit_doc_ids=True)` to be warned each time it is applied. (A `@document` that already ends in `/`, `#`, or `?` concatenates directly, with no inserted `#`.)

### Vocabulary prefixes (`@iri`)

When a document uses more than one vocabulary base (for example schema.org plus a project-specific ontology), declare additional prefixes under `@iri`:

```
* @iri:
    * acme: https://acme.example.com/kg/schema
    * schema: https://schema.org
```

Each nested line is `prefix: namespace-base`, where `prefix` is a QName-style NCName (letters, digits, `_`, `.`, `-`) and `namespace-base` is the IRI prefix string that local names append to. The same block may also repeat `@nodebase`, `@schema`, or `@typebase` as nested lines (they update the corresponding document fields).

Use **compact CURIEs** anywhere an IRI label or type is expected:

- `acme:Client` in a type position → `https://acme.example.com/kg/schema/Client` (with the example bases above)
- `<acme:contactPoint>` as a property or edge label → `https://acme.example.com/kg/schema/contactPoint`
- Bare names such as `name` still resolve against `@schema` when no matching `@iri` prefix applies

**`@schema` and the `schema` prefix:** Top-level `@schema` automatically registers `schema` in the internal prefix map used for CURIE expansion, so `schema:name` and bare `name` resolve to the same IRI. You do not need to repeat `* schema: …` under `@iri` unless you want it visible for readers. If you do declare `schema:` under `@iri`, it must match `@schema` after normalization (trailing `/` ignored); otherwise parsing fails with `SchemaPrefixConflict`.

**CURIE** namespace joining (under `@iri`) follows RDF/XML rules: if the prefix base already ends with `/`, `#`, or `?`, the local name is appended directly (no extra `/`); otherwise a single `/` is inserted between base and local name. So `@iri` prefix bases should usually be written **without** a trailing slash unless the vocabulary IRIs are defined that way. This differs from the bare-name `@nodebase`/`@schema`/`@typebase` bases above, which join by pure concatenation and therefore *must* carry their own trailing separator. The two converge for any base that ends in a separator — which is why the auto-registered `schema:` prefix and bare names agree for the usual trailing-slash `@schema`.

Onya built-in names use a leading `@` and the Onya vocabulary (e.g. `@document`, `@source`), not the `@iri` map.

Example (Acme client with schema.org contact details):

```
# @docheader

* @document: https://acme.example.com/pulse/kg/sample
* title: Coyote Corp (Acme client)
* @nodebase: https://acme.example.com/pulse/kg/sample/
* @schema: https://schema.org/
* @iri:
    * acme: https://acme.example.com/kg/schema
    * schema: https://schema.org

# Coyote [<acme:Client>]

* name: Coyote Corporation
* url: https://www.coyote.example/
* <acme:contactPoint> -> acme-cp-main

# acme-cp-main [ContactPoint]

* contactType: main
* name: Jane Doe
* email: jane.doe@acme.example
```

## Node Blocks

Each node block defines a node:

```
# NodeID [Type]

* label: value
<!-- Additional assertions -->
```

Structure:
- Header: `# NodeID [OptionalType ...]`
  - `NodeID` is resolved relative to `@nodebase` (or `@document` if `@nodebase` is not set)
  - The bracketed portion holds the node's **types**, which form a *set*. Zero or
    more types may be given, **space-separated** (e.g. `# acme [Organization lv:Client]`).
    Each type is resolved independently relative to `@typebase` (or `@schema` if
    `@typebase` is not set), and each may be a bare name, a CURIE (`lv:Client`), or an
    explicit `<…>`-wrapped IRI/CURIE. Duplicate types collapse into the single set entry.
- Assertions: list items starting with `*`
  - `label: value` - property (label is IRI, value is string)
  - `label -> TargetID` - edge (label is IRI, TargetID is node ID).
    The Unicode arrow `→` (U+2192) is accepted as a synonym for `->`.
- Indentation indicates nested assertions

## Example: Things Fall Apart

```
# @docheader

* @document: http://example.org/classics/things-fall-apart
* title: Things Fall Apart knowledgebase
* @nodebase: http://example.org/classics/
* @schema: https://schema.org/
* @language: en

# TFA [Book]

* name: Things Fall Apart
* alternateName: TFA
* isbn: 9781841593272
* datePublished: 1958-06
* bookFormat -> Paperback
* author -> CAchebe
* publisher -> Heinemann

# CAchebe [Person]

* name: Chinua Achebe
* birthDate: 1930-11-16
* birthPlace -> Ogidi
* jobTitle: Novelist

# Heinemann [Organization]

* name: William Heinemann Ltd.
* foundingDate: 1930
* foundingLocation -> London
  * country -> UK
```

## Recursive Assertions Example

Assertions can have nested assertions:

```
# Boston [City]

* name: Boston
  * stateCode: MA
  * country -> USA

Keys to demonstrate qualified values:
* temperature: 25
  * unit: Celsius
  * measurementMethod -> InfraredThermometer
```

In the second example, the `temperature` property has two nested assertions:
- A property `unit` with value "Celsius"
- An edge `measurementMethod` pointing to an `InfraredThermometer` node

## Explicit IRIs

You can use explicit IRIs with angle brackets:

```
* <https://schema.org/name>: Chinua Achebe
```

## Quoted Values

String values can be explicitly quoted:

```
* name: "Things Fall Apart"
* description: "A novel about pre-colonial Igbo society"
```

Use quotes when values contain special characters or when you want to explicitly mark something as a string.

## Long Text Blocks

Onya Literate supports two mechanisms for handling long text blocks as property values:

### 1. Markdown Indented Text

Use Markdown's standard mechanism for multi-line list items. After the initial property line, add blank lines followed by indented paragraphs (4+ spaces) to continue the text within the same bullet point:

```
# CAchebe [Person]

* name: Chinua Achebe
* bio: Chinua Achebe (1930–2013) was a Nigerian writer considered a founder of modern African literature.

    Known for his novel Things Fall Apart and for writing about African life from an African perspective, his work focused on the effects of colonialism, political corruption, and the clash between traditional and Western values.

    After the Nigerian Civil War, he became an English professor in the United States before returning to Nigeria to continue his academic and writing career.
* birthDate: 1930-11-16
```

The indented paragraphs are treated as part of the same property value, with newlines preserved.

### 2. Text References

For longer text blocks or when you want to define text content separately from its usage, use text references with Python-style triple quotes:

```
# CAchebe [Person]

* name: Chinua Achebe
* bio:: achebe-bio  <!-- The double colon marks it as a text reference -->
* birthDate: 1930-11-16

:achebe-bio = """Chinua Achebe (1930–2013) was a Nigerian writer considered a founder of modern African literature, known for his novel Things Fall Apart and for writing about African life from an African perspective.

His work focused on the effects of colonialism, political corruption, and the clash between traditional and Western values, with works like Things Fall Apart and the "African Trilogy" exploring the Igbo experience. After the Nigerian Civil War, he became an English professor in the United States before returning to Nigeria to continue his academic and writing career.
"""
```

Text references:
- Use `::` after the property label to indicate a text reference
- Define the text content with `:reference-name = """content"""`
- Text references can be defined anywhere in the document, not necessarily before their usage
- Triple-quoted content preserves all whitespace and newlines exactly as written

## Serialization (`onya.serial.literate.write`)

Graphs can be written back to Onya Literate with `write()`. Supply the same bases used when authoring:

- `document`, `nodebase`, `schema` — written in `# @docheader`
- `prefixes` — extra vocabularies under `@iri` (the `schema` prefix is implied by `schema=` and is not repeated under `@iri`)
- `bracket_curie` — if true, non-schema labels use `<prefix:local>`; default is `prefix:local` (e.g. `acme:contactPoint`)
- `bracket_types` — if true, types use bracketed CURIE form in headers

Document-level properties stored on the document node are emitted as top-level docheader bullets. The document node itself is not written as a `#` block.

## Optional assertion provenance (`@source`)

Some workflows want document-level provenance without making it part of the core model. The parser can optionally tag **every created assertion** (including nested assertions but excluding document header declarations) with a sub-property:

- `@source`: the `@document` IRI of the source document

Parsers will generally turn this **off by default** to avoid graph bloat.

## Model Summary

```
Graph
  └── Node (identified by IRI)
      ├── types: set[IRI]
      ├── properties: set[Property]
      └── edges: set[Edge]
      
Property (assertion: origin + label, anonymous by default)
  ├── origin: Node | Property | Edge
  ├── label: IRI
  ├── value: str
  ├── id: IRI | None        (absent by default; see Assertion Identifiers)
  ├── properties: set[Property]
  └── edges: set[Edge]

Edge (assertion: origin + label, anonymous by default)
  ├── origin: Node | Property | Edge
  ├── label: IRI
  ├── target: Node
  ├── id: IRI | None        (absent by default; see Assertion Identifiers)
  ├── properties: set[Property]
  └── edges: set[Edge]
```

# Design Principles

1. **Simplicity**: Core model uses only nodes, edges, and properties
2. **IRI-based**: All identifiers are IRIs for global uniqueness
3. **String values only**: Keep the core model simple; add typing in layers above
4. **No pervasive ordering**: Use sets for assertions; ordering can be added when needed
5. **Recursive assertions**: Edges and properties are first-class, can have their own assertions
6. **Graph, not model**: The container is a "graph", elements within use "assertions" terminology

# Relationship to Other Models

Onya is similar to RDF but simpler:
- Similar: IRIs, triples (s-p-o), reification via recursive structure
- Simpler: No literals beyond strings, no blank nodes, uniform treatment of properties/edges
- Different: Assertions are anonymous by default but may be given an identifier on demand; properties are always strings

The recursive assertion model is reminiscent of property graphs but more uniform:
- Similar: Nodes and edges both can have properties
- Different: Properties can also have edges, all via the same mechanism
