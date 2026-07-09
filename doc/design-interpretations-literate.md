# Design: Interpretations in Onya Literate

Status: draft for implementation. Companion to
[design-interpretations-strings-vs-typing.md](design-interpretations-strings-vs-typing.md)
(motivation and principles) and
[design-interpretations-pylib.md](design-interpretations-pylib.md)
(Python plugin layer). This document specifies syntax and model-level
semantics; it is intended to be precise enough to drive implementation.

## Summary

Every Onya value is a string, always. An **interpretation** is a recorded hint about how a string value is meant to be read (as a number, a date, an IRI, and so on). In Onya's architectural language, an interpretation is a single data contract: a promise attached by the author, checked—if ever—at a boundary the consumer chooses (see the strings-vs-typing design doc).

This document adds:

1. An inline declaration, `@as`, nested under a property — names the
   interpretation for that one value.
2. A document-level `@interpretations` stanza in `@docheader` — names a
   default interpretation for every property with a given label in the
   document.
3. One new model attribute: each assertion carries `interp`
   (an IRI, or none), alongside the existing optional `id`.

The concept is called *interpretation* everywhere in prose and vocabulary.
The literate keyword is `@as`, chosen for readability: `* age: 28` followed
by `* @as: number` reads as ordinary language.

Interpretations are never applied during parsing. Parsing records them;
a separate layer (see the pylib design doc) checks or converts values only
when an application asks.

## Lineage, briefly

Versa had a `@interpretations:` docheader stanza mapping property labels to
interpretation keys, which is inherited here nearly intact. But Versa
applied interpretations *eagerly at parse time*, mutating what the model
stored (e.g. `@resource` stored an IRI object instead of a string). Onya
deliberately rejects that: the model always stores the string, and the
interpretation travels beside it as data. Two parsers with different
plugin configurations must produce identical models.

## Inline declaration: `@as`

`@as` is a **directive**, exactly like `@id`: nested one level under a
property, it annotates that property without creating a property on it.

```
# Chuks [Person]

* age: 28
  * @as: number
* birthDate: 1998-03-15
  * @as: datetime
```

Rules:

- `@as` is valid nested under a **property** (including a property nested
  on an edge or on another assertion, at any depth). The value of an edge
  is a node, not a string, so there is nothing to interpret: `@as` nested
  directly under an edge is ignored with a parse warning. The syntax
  position is reserved in case a future revision finds a meaning for it.
- A property has at most one interpretation. A second `@as` on the same
  property is a parse error.
- `@as` may appear alongside `@id` and alongside ordinary nested
  assertions, in any order.
- The interpretation does not create a property: after parsing, the
  property above has zero nested properties, `interp` set, and its value
  is still exactly the string `28`.

## Interpretation names

The value of `@as` (and of docheader declarations) names an interpretation.
Resolution, in order:

1. **Reserved bare names.** The tokens `number`, `datetime`, `boolean`,
   `iri`, `text`, and `none` resolve to IRIs in the Onya interpretation
   vocabulary (managed with the rest of the Onya vocabulary via purl.org;
   the Python constant is `ONYA_INTERP(name)`). These correspond to the
   Onya Lightweight Types starter set — see the pylib design doc for what
   each accepts.
2. **Anything else** is an IRI reference, resolved through the document's
   existing IRI machinery (absolute IRIs pass through; abbreviations
   declared via `@iri` apply). It is **never a parse error** for the name
   to be unknown to the local software: the IRI is recorded and travels
   with the data.

`none` is special: it names no interpretation. Its only purpose is to
cancel a document-level default on one particular property (see
precedence, below). It is not stored: a property whose declarations
resolve to `none` has `interp` unset, indistinguishable from a property
that never mentioned interpretation at all.

## Document-level defaults: `@interpretations`

A stanza in `@docheader`, directly inheriting the Versa shape:

```
# @docheader

* @document: http://example.org/people-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/
* @interpretations
  * age: number
  * birthDate: datetime
  * url: iri
```

Rules:

- Each nested line maps a **property label** to an interpretation name.
  The label (left side) resolves against `@schema` exactly as assertion
  labels do; the interpretation name (right side) resolves as described
  above.
- The declaration applies to every property in the document whose resolved
  label matches — at node level and nested at any depth.
- Multiple declarations for the same resolved label within one docheader:
  parse error.

## Precedence

For any single property, from strongest to weakest:

1. Inline `@as` on the property itself (`@as: none` cancels a default).
2. The document's `@interpretations` declaration for the property's label.
3. Nothing: `interp` unset.

## Desugaring: the model carries only per-assertion interpretation

This is the load-bearing rule. Document-level declarations are
**serialization-layer sugar**. At parse time, each property's effective
interpretation (after precedence) is written to that property's `interp`
attribute, and the docheader stanza is then discarded — it is not part of
the graph. Consequences, all intended:

- The graph model has one mechanism, not two. Queries, merge, and the
  interpretation layer never consult document context.
- Hints survive graph merge, because they travel on assertions, not on
  documents whose headers are long gone by merge time.
- Two documents with different `@interpretations` defaults merge without
  any rule for reconciling headers — there are no headers to reconcile.

## Serialization (round-trip)

- Phase 1: `write()` emits an inline `@as` line for every property whose
  `interp` is set, mirroring how `@id` is emitted today. Round-trip
  (write then read) must reproduce `interp` on every assertion.
- Phase 2 (optional, for readability of emitted documents): the writer MAY
  factor interpretations that are uniform for a given label across the
  whole graph into a generated `@interpretations` stanza, emitting inline
  `@as` only for exceptions — including `@as: none` for a property that
  lacks an interpretation its label's generated default would otherwise
  supply. Factoring must be exactly model-equivalent to the inline form.

## Merge semantics (amendment to SPEC § Identity and graph merge)

`interp` is excluded from the assertion **skeleton**, like nested
assertions and like `id`: adding or removing an interpretation never
changes an assertion's identity. Rule 2 (anonymous assertions with equal
skeletons merge) is amended with a compatibility condition:

- If neither has `interp`, or both have the same `interp`: merge; the
  merged assertion keeps that state.
- If exactly one has `interp`: merge; the merged assertion adopts it.
- If both have `interp` and they differ: **do not merge** — the two
  remain distinct assertions. This is not an error; two sources attaching different contracts to the same string are making genuinely different claims, and a merge must not quietly pick a winner. The disagreement stays in the graph, visible to queries and to `validate()`.


Rule 1 (same explicit `id` ⇒ same assertion) gains the parallel condition:
differing non-absent `interp` values on same-id assertions is a merge
error, consistent with the existing skeleton-mismatch rule.

## Deferred (with sketches, not commitments)

- **Including declarations from another file.** Something like a nested
  `* @include: <IRI>` inside the `@interpretations` stanza, pulling in
  declarations from another Onya Literate document's docheader. Deferred
  because it raises fetching, relative-resolution, and trust questions
  that deserve their own design pass — and because desugaring means it
  would be purely an authoring convenience, adding no model power.
- **Parameterized interpretations** (e.g. language-tagged text, units).
  A name-plus-arguments form complicates resolution and the registry
  contract; language handling in particular should be designed together
  with the existing `@lang` machinery rather than bolted on here.
- **Inline abbreviation.** If the `@id` inline-sugar ticket (bracket
  idiom) lands, `@as` should get the matching treatment in the same pass.

## Test checklist (parser-facing)

- `@as` under a property sets `interp`; creates no nested property.
- `@as` under an edge: warning, ignored, parse succeeds.
- Duplicate `@as` on one property: parse error.
- Unknown interpretation IRI: parses clean, `interp` carries the IRI.
- Docheader default applies to matching labels at node level and nested.
- Inline `@as` beats docheader default; `@as: none` cancels it.
- Duplicate label in `@interpretations` stanza: parse error.
- Round-trip preserves `interp` for inline (phase 1) and factored
  (phase 2) forms.
- Merge: one-sided interp adopts; equal merges; conflicting stays distinct.
