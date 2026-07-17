# Changelog
<!--
Notable changes to Onya are recorded here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For interim changes not yet earmarked for a particular release, can use this header at the top:
## [Unreleased]
-->

## [0.4.1] - 20260716: Wildcard selector query method. networkx projection + analytics write-back. Stray edge-arrow diagnostics.

### Added

- **Stray edge-arrow diagnostics.** The only valid edge connectors are ASCII `->` and `→` (U+2192); a near-miss (`➡` U+27A1, `⟶` U+27F6, `↦` U+21A6, `⇨` U+21E8, `⇒` U+21D2, ASCII `=>` / `-->`, and other common rightward arrows) previously produced an opaque `pyparsing` "Expected end of text" failure that named neither the character nor the line. The parser now recognizes these on the failing list item and, by default, raises **`EdgeArrowError`** (importable from `onya.serial.literate`) naming the offending character + codepoint and showing the corrected line for cut & paste. `LiterateParser(lenient_arrows=True)` / `read(..., lenient_arrows=True)` instead accepts the stray arrow as an edge, emits a `UserWarning`, and parses on. The check is gated on an actual parse failure, so an arrow sitting inside a property value never triggers it, and any non-arrow failure re-raises unchanged. The `onya convert` CLI gains `--lenient_arrows` and, in strict mode, prints just the friendly message (no traceback) and exits non-zero.
- **`graph.select()` — the uniform single-pattern selector** (closes the "round out `match()`" gap, lineage back to 4RDF's `complete()`). Yields the actual `assertion` objects whose components match every supplied constraint, `None` wildcarding each: `origin` (node/assertion, by id or object identity), `label`, `value` (restricts to properties — the property face of the object slot), `target` (restricts to edges, matching a target node id or an identified assertion's `@id` — the edge face), `id` (select by assertion `@id`), and `deep=` to descend into nested/reified assertions. `value=` and `target=` are Onya's structural split of RDF's single object position, so passing both is a `ValueError`. Returning live objects (drawn from a per-container snapshot) means a caller can read `id`/`interp`/nested assertions off a result or `remove_property`/`remove_edge` it mid-iteration — the 4RDF remove-iterate idiom. `graph.match()` is now the tuple-projection view over `select()`: its `origin`/`label` arguments became optional wildcards (a widening, not a break), and its `(origin, relation, target, annotations)` shape is unchanged. SPEC § Selecting assertions documents the model-level capability (Tier 1; paths/joins/transitivity remain a layer above).
- **`onya.serial.nx` — networkx projection + analytics write-back**, extras-gated (`pip install "onya[nx]"`; networkx imported lazily, so the base install stays dependency-free). An analytics peripheral in the same architectural sense as `onya.store`: it imports the core, never the reverse (enforced by the layering guards).
  - **`to_networkx(g, *, apply_interps=False, registry=None)`** projects into a `networkx.MultiDiGraph` (always; `networkx.DiGraph(to_networkx(g))` collapses parallel edges). **Lossy by design (v1, first-level structure):** node → nx node keyed by `str(node.id)` with `types` (tuple of str IRIs) and each property as a **list-valued** attr keyed by `str(label)` (multi-valued properties stay honest lists); edge → nx edge with an **auto-assigned key** (parallel same-skeleton edges stay distinct — the projection reflects the graph as-is; call `g.merge()` first for a normalized view), `label` attr, and first-level edge properties as list attrs. Edges whose target is an identified assertion are skipped (one aggregated warning); nested assertions below the first level are dropped. `apply_interps=True` passes values through `onya.interp.value_of(..., strict=False)` so e.g. `@as: number` arrives as `int`/`Decimal`; unknown interpretations fall back to the raw string.
  - **`write_back(g, label, values, *, interp=None, registry=None, replace=True) -> int`** records results (a node-id → Python object mapping, e.g. `networkx.betweenness_centrality` output) back as properties, returning the count written. `interp` (e.g. `ONYA_INTERP('number')`) renders via `onya.interp.set_value` so the value carries its contract; `interp=None` writes `str(py_obj)`. `replace=True` (default) makes re-running analytics idempotent; `replace=False` accumulates; unknown node ids are skipped. The round trip makes analytics first-class Onya data — queryable via `graph.select`, merge-safe through `store.put(name, g, merge=True)`. See `demo/nx_analytics/`.

### Fixed

- **The document node is now first-class in Onya Literate.** Its `@docheader` bullets carry the same expressiveness as any node block — `@as` interpretations, `@id`, nested/reified assertions, and edges — on both parse and serialize, and `@interpretations` defaults apply to them. Previously the docheader was parsed and written as a restricted *flat* `label: value` form, so an interpretation, an `@id`, a nested assertion, or an edge on the document node was silently dropped or misparsed (e.g. `* about -> Thing` became a string property, creating no edge or target node) and lost on `write → read`. Parse and serialize now route document-node assertions through the same machinery as body nodes (`_build_assertions` / `_write_assertions`); only the document node's identity and implicit `onya:Document` type stay directive-driven (`@document`), so it still has no `# NodeID [Type]` header and is never emitted as a separate `#` block. SPEC § Document Header documents this. (#26)

## [0.4.0] - 20260709: Graph merge. Data contract layers. Asserdion IDs. Empty node blocks. Multi-typed nodes. Persistence store.

### Added

- **`onya.store` — pluggable persistence for Onya graphs.** A store is *correct* exactly when a round trip through it is indistinguishable from an in-memory graph union; storage is a peripheral (`onya.store` imports the core, never the reverse — enforced by a layering test). `connect(url)` dispatches on URL scheme through the `onya.store.backends` entry-point group; an unknown scheme raises `ValueError` naming the known schemes.
  - **`GraphStore`** base protocol (`put`/`get`/`drop`/`names`, async context manager) plus optional `runtime_checkable` capability protocols **`AssertionStore`** (`match`/`subgraph`/`add`/`remove`) and **`GraphQueryStore`** (`graph_table`), discovered by `isinstance`.
  - **Filesystem backend** (`file:`, default; the testing fake): one Onya Literate file per named graph under a root dir, atomic writes (temp + `os.replace`), a `.lock` sidecar for light concurrency. `put(merge=True)` is literally *parse existing, union in memory, re-serialize*, so it is the executable spec the SQL backends are tested against.
  - **SQLite backend** (`sqlite:`, stdlib, no added dependency): one serialized writer connection via `asyncio.to_thread`, WAL, foreign keys on. Satisfies `GraphStore` + `AssertionStore`.
  - **PostgreSQL backend** (`postgresql://`, extras-gated `onya[postgres]` → asyncpg imported lazily): connection pool, schema migration on connect, and — automatically on PostgreSQL ≥ 19 — SQL/PGQ property graph definitions (`onya_base`, `onya_reified`) so the store also satisfies `GraphQueryStore`; a canned `reachable()` recursive-CTE helper for transitive traversal.
  - **Merge is the write semantics**: `put(merge=True)` unions with the stored graph under SPEC merge Rules 1–3 plus the interp amendment (including the ratified NULL-adopts ruling). The shared relational core (`onya.store._relational`) holds the dialect-parameterized DDL, **skeleton hash v1** (versioned in `onya_meta`; an unrecognized version refuses to open), and the write-path merge algorithm.
  - `onya.store.sync` — a minimal blocking facade (per-call `asyncio.run`, context-manager lifecycle) for scripts and REPL use.
- **Model-level graph union** — `graph.union(other)` folds another graph in and normalizes per the SPEC identity rules (the operation every backend's `put(merge=True)` is defined against). `graph.validate_id_space()` surfaces a node-id vs assertion-`@id` collision as `AssertionIdConflict`.
- **Data contract layers** — the value-level slice of "data contract": a named **interpretation** (a recorded promise about how a string value is meant to be read) attachable to any property, honored at boundaries a consumer chooses, never ambiently. The graph's string layer stays unconditionally valid: nothing here mutates a stored value, rejects a parse, or varies the model by installed plugins.
  - **`@as` directive** (SPEC § `@as`): a nested `* @as: name` records an interpretation on its enclosing property (like `@id`, it creates no property). Valid on properties at any depth; on an edge it is ignored with a warning (an edge's value is a node). A duplicate `@as` on one property is a parse error. Reserved bare names `number`, `datetime`, `boolean`, `iri`, `text` resolve into the Onya interpretation vocabulary (`ONYA_INTERP(name)` in `onya.terms`); `none` cancels a default and is never stored; anything else resolves as an IRI (absolute IRIs pass through, `@iri` abbreviations apply). An **unknown interpretation is never a parse error** — the IRI travels with the data.
  - **`@interpretations:` docheader stanza** mapping property labels to interpretation names (Versa lineage, minus Versa's parse-time coercion). It is pure sugar: at parse time each effective interpretation (precedence: inline `@as` > docheader default > nothing) is desugared onto the property's `interp`, and the stanza is discarded — the model carries only per-assertion contracts, so merge needs no header logic. A duplicate label in the stanza is a parse error. (The block header is written with a trailing colon, `@interpretations:`, like `@iri:`.)
  - Assertions gain an `interp` slot (`None` by default), excluded from the merge skeleton like `id`. `add_property(label, value, interp=None)` grows the keyword. `write()` emits `@as` for every interpreted assertion at every depth, rendering reserved names back to bare form and IRIs through declared abbreviations (a pure model operation — the writer never consults a registry).
  - **`onya.interp`** plugin layer (imported by nothing in the core model or parser): the `Interpretation` protocol (`check`/`to_python`/`from_python` with a round-trip law), `InterpretationRegistry` + module-level `DEFAULT`, the **Onya Lightweight Types** starter set (`number` — `int`/`Decimal`, never binary `float`; `datetime`; `boolean`; `iri`; `text`), and an application API honored on demand: `value_of` (strict/non-strict on unknown contracts), `set_value` (builder inverse), `validate` → `ValidationReport` (a failed check is a **finding**, never an exception), and `unknown_interps`. `InterpretationError` / `UnknownInterpretation` carry the value, interp IRI, and assertion.
- Explicit **assertion identifiers** via the `@id` directive (SPEC § Assertion Identifiers). A nested `* @id: name` names an edge or property — resolved against `@nodebase`, sharing the node id space — rather than creating a property on it. Once named, the assertion is a valid edge target (`* disputes -> name` links to the assertion, not a fresh node), and references resolve regardless of declaration order. Identifiers must be unique within the graph: a duplicate `@id`, or an `@id` that collides with a node id, raises `AssertionIdConflict` (importable from `onya.serial.literate`). `write()` emits `@id` for identified assertions so they round-trip. Assertions gain an `id` attribute (`None` by default); graphs gain an `assertion_ids` map and `register_assertion_id()`.
- Implicit `onya:Assertion` type (`ONYA_ASSERTION` in `onya.terms`) carried, read-only, by every assertion as `types` — uniform with `node.types` and the type check that interprets an edge target resolved via `assertion_ids` (node vs. identified assertion). `graph.match()`'s docstring documents the pattern.
- Empty node blocks (a `#` header with no type and no assertions) now parse instead of raising, fixing a `write()`→`read()` round-trip failure for target-only nodes. By default this warns (`node block … is empty …`); silence it with `LiterateParser(warn_empty_blocks=False)`.

### Changed

- **Graph merge is now implemented** (SPEC § Identity and graph merge) as an explicit, on-demand operation: `graph.merge()` collapses duplicate assertions into a single occurrence — anonymous assertions with equal skeletons union their nested assertions recursively; assertions sharing an `id` merge and must agree (`GraphMergeError`, importable from `onya.graph`); an identified assertion never merges with an anonymous one. Parsing does **not** merge: overlapping documents parsed into one graph accumulate their assertions as distinct occurrences and collapse only when the caller invokes `merge()` (never ambiently — consistent with the interpretation layer). The interpretation compatibility condition rides on this: equal-or-one-absent `interp` merge (one-sided adopts the present interp); differing `interp` on anonymous assertions blocks merge and the two stay distinct (not an error); differing non-absent `interp` on same-`id` assertions is a `GraphMergeError`. `LiterateParser.parse()` and `read()` take an opt-in `merge=False` keyword as a one-call shorthand for the common parse-then-merge workflow.

### Fixed

- **Onya Literate serializer now round-trips awkward string values.** `write()` escapes `"`/`\` in quoted values and emits multi-line text as triple-quoted text references, so values with newlines, embedded quotes, or backslashes survive `write → read` byte-for-byte. Triple-quoted text-reference values now store their *inner* content (the `"""` delimiters were previously kept in the value, which was both surprising and un-round-trippable), and a quoted docheader property value is stored as a plain `str` (matching body assertions) rather than a `LITERAL`.
- **Multi-typed nodes now round-trip.** A node's types form a *set*, and `write()` already emitted them space-separated inside the header brackets (`# acme [Organization lv:Client]`), but the parser expanded the whole bracket group as one IRI — so any graph with a multi-typed node failed `parse → write → parse` and a hand-authored multi-type header raised an opaque error. The parser now tokenizes the bracket content into individual type refs (whitespace-separated, keeping `<…>` wrappers whole), expands each independently, and adds all to `node.types`. SPEC § Node Blocks documents the space-separated multi-type syntax.
- Onya Literate now handles **arbitrary nesting depth** on both read and write. The parser tracks nesting with an indent stack (previously it collapsed everything below the first level onto that level), so a deeply-nested assertion attaches to its true parent and a nested `@id` names the assertion it is written under (not the top-level one). `write()` is now recursive and emits nested **edges** (previously dropped) and `@id` at every level, so nested assertions — including identified ones and nested n-ary/qualified structures — round-trip.

## [0.3.1] - 20260615: Strict namespacebases.

### Added

- `NamespaceBaseError` (importable from `onya.serial.literate`) and a `LiterateParser(strict_namespace_bases=True)` flag. Bare node ids, labels, and types join to `@nodebase`/`@schema`/`@typebase` by pure concatenation, so a base without a trailing separator mints mashed IRIs (`@nodebase https://ex.org/g` + `Node` → `https://ex.org/gNode`). Strict mode rejects such a base with `NamespaceBaseError`.
- Implicit `#` separator for the `@nodebase`→`@document` fallback: when `@nodebase` is omitted and `@document` lacks a trailing separator, relative node ids resolve as `@document` + `#` + id (e.g. `…/things-fall-apart` + `TFA` → `…/things-fall-apart#TFA`) instead of mashing. Silent by default; `LiterateParser(warn_implicit_doc_ids=True)` warns on each application.

### Deprecated

- An explicit `@nodebase`/`@schema`/`@typebase` that does not end in `/`, `#`, or `?` now emits a `DeprecationWarning` (and raises `NamespaceBaseError` under `strict_namespace_bases=True`). A future release will make strict the default. The `@nodebase`→`@document` fallback is exempt. (Distinct from `@iri` CURIE prefixes, which get RDF/XML separator insertion and so are written without a trailing slash.)

### Changed

- Onya Literate parser migrated to PEP8 pyparsing API names (`parse_string`/`parse_all`, `set_parse_action`, `leave_whitespace`, `set_default_whitespace_chars`, `html_comment`, `esc_char`, `DelimitedList`). No behavior change; removes `PyparsingDeprecationWarning`s and keeps the parser working under the upcoming pyparsing 4.0, which drops the legacy pre-PEP8 aliases.

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

- `onya.util.compact_iri(…, bracket=False)` now returns the bare IRI (not bracketed) when no prefix matches and the caller has explicitly opted out of bracketing — previously both branches returned `<full>`
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
