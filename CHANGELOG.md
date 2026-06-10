# Changelog

Notable changes to  Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
## [Unreleased]
-->

## [0.3.0] - 20260610: Cleanup & AI aids

### Added

- `ONYA_DOCUMENT` term in `onya.terms` for document node type
- `ONYA_SOURCE_REL` term in `onya.terms` for `@source` provenance sub-properties
- Onya Literate **compact CURIE** expansion (`prefix:local` and `<prefix:local>`) using prefixes declared in the document `@iri` block; namespace joining avoids duplicate `/` when the base already ends with `/`
- `@schema` auto-registers the `schema` CURIE prefix in `doc.iris`; mismatch with explicit `schema:` under `@iri` raises `SchemaPrefixConflict`
- `onya.util`: `namespace_for_curie`, `join_namespace`, `curie_local_for_iri`, `compact_iri`, `shorten_node_id`
- `literate.write()` rewrite: docheader, types, edges, nested assertions, CURIE labels (`bracket_curie` / `bracket_types` flags)
- `onya.serial.literate.read()` implemented as a thin shim over the parser; accepts a string or a file-like object and returns a `ParseResult`
- `LiterateParser`, `ParseResult`, `SchemaPrefixConflict` are now importable from `onya.serial.literate` (canonical public path)
- Unicode `→` (U+2192) accepted as a synonym for `->` in edge assertions (documented in SPEC)
- Aligned to Oori's coding-agent-control: `oori-seed-repo . --kind python,python-prompting,onya-graph  --tools claude,opencode`

### Changed

- `mermaid.write()` / `graphviz.write()` / CLI `onya convert`: kwargs renamed `base` → `nodebase`, `propertybase` → `schema`, with optional `prefixes` for additional CURIE prefixes. All label/type abbreviation now goes through `compact_iri`, which handles Onya `@`-vocab built-in
- Parser internals moved to `onya.serial._literate_parse` (private). User code should import from `onya.serial.literate`

### Removed

- Legacy `@prefix/path` abbreviation form (use compact CURIEs `prefix:local` or `<prefix:local>` instead)
- `@type-base` and `@resource-type` aliases for `@typebase`
- `literate.write()` deprecated `base` / `propertybase` aliases (use `nodebase` / `schema`)
- `onya.util.abbreviate()` (use `compact_iri` and `shorten_node_id`)
- Unused `onya.serial.litparse_util` and `onya.contrib.mkdcomments` modules; `markdown` dropped from runtime dependencies
- Module-level `parse()` shim in the parser (use `LiterateParser().parse(...)` or the new `read()`)

### Fixed

- `onya.util.compact_iri(..., bracket=False)` now returns the bare IRI (not bracketed) when no prefix matches and the caller has explicitly opted out of bracketing — previously both branches returned `<full>`
- Duplicate self-assignment `RDF_TYPE = RDF_TYPE = ...` in `onya.terms` collapsed to a single assignment
- Loop variable `prop_info` in `process_nodeblock` no longer shadows the `prop_info` dataclass
- CURIE expansion is evaluated before Onya `@` vocabulary names, so prefixed terms such as `acme:Client` are not mistaken for Onya built-ins
- Document nodes created from `@document` directive now automatically receive `onya:Document` type
- Test case against missing `onya:Document` regression


## [0.2.0] - 20251216

### Added

- Class-based Onya Literate parser API: `LiterateParser`, returning a `ParseResult` with `doc_iri`, `graph`, and `nodes_added` (originally exported from `onya.serial.literate_lex`; later canonicalized at `onya.serial.literate`)
- Optional assertion provenance: `document_source_assertions` flag to add `@source` sub-properties on created assertions (including nested assertions)
- Graphviz (DOT) serializer: onya.serial.graphviz.write(), incl. styling options, IRI abbreviation, and optional edge annotations
- Mermaid (flowchart) serializer: `onya.serial.mermaid.write()`, incl. IRI abbreviation, optional edge annotations, and basic type-to-shape mapping
- Mermaid demo: `demo/mermaid_basic/` (parallel to `demo/graphviz_basic/`)
- `onya` CLI (console script): `onya convert <filespec>` to emit Mermaid (`--mermaid`) or Graphviz DOT (`--dot`) from Onya Literate input (path/glob/dir/stdin)
- Preliminary graph.match() method
- Files: LICENSE, CONTRIBUTING.md and this very CHANGELOG.md 😆

### Changed

- Prefer `@nodebase` over legacy `@base` in `@docheader` for node ID resolution; if `@nodebase` is omitted, node IDs resolve relative to `@document`
- Parsing a document with `@document` now creates/ensures a node for the document IRI (and attaches other docheader assertions to it)
- Documentation/examples updated to use the class-based parsing API

### Fixed

- Onya Literate `->` edges now create edges even when the RHS is a plain (relative) node ID (e.g. `knows -> B`)
- onya.serial.literate.write()

## [0.1.1] - 20251118

- Initial public release
