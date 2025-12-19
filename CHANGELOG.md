# Changelog

Notable changes to  Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
## [Unreleased]
-->

## [Unreleased]

### Added

- `ONYA_DOCUMENT` term in `onya.terms` for document node type

### Fixed

- Document nodes created from `@document` directive now automatically receive `onya:Document` type
- Test case against missing `onya:Document` regression


## [0.2.0] - 20251216

### Added

- Class-based Onya Literate parser API: `onya.serial.literate_lex.LiterateParser`, returning a `ParseResult` with `doc_iri`, `graph`, and `nodes_added`
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
