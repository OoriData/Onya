**Design document: the canonical content digest**

A projection that hashes its output rows can say "the tables changed". It can't say "the knowledge graph changed", and it can't be recorded as the KG version in provenance. This document defines a hash of the graph itself, implemented by `onya.digest`.

It answers one question: *do these two graphs say the same thing?* SPEC defines that as **graph equivalence** (the same union-normalized content). The digest is a hash of the equivalence class: equivalent graphs have the same digest, and (barring a SHA-256 collision) only equivalent graphs do.

It is not the store's `skeleton_hash`. That is a *merge-identity* hash (origin, label, target-or-value), and leaves out `@id` and interpretations on purpose, because annotating an assertion must not change which assertion it is. A digest must see exactly those things.

## Use

```python
from onya.digest import digest, node_digests, DEFAULT_EXCLUDE

digest(g)                          # 'sha256:9f2c...'
digest(g, nodes=[iri1, iri2])      # a subset, for incremental re-projection
node_digests(g)                    # {iri: 'sha256:...'}: diff two versions cheaply
digest(g, exclude=DEFAULT_EXCLUDE | {'ex:internalNote'})
```

## Definition

Over the graph's **union-normalized** content, using full IRIs only (never prefixes, serialized forms or `@nodebase`):

```
assertion = H('A', kind, label, value-or-target-id, interp, id, sorted child digests)
node      = H('N', id, sorted types, sorted assertion digests)
graph     = H('G', sorted node digests)
```

- `kind` is `p` or `e`; `interp` and `id` are the empty string when absent. The target of an edge is its node id, or the id of the identified assertion it points to, never the target's content, so a node's digest depends only on the node.
- `H` is SHA-256 over the tag, each field as 8-byte length plus UTF-8 bytes, an 8-byte count of children, then the children's raw digests in sorted order. The lengths and count make the encoding unambiguous: `('ab', 'c')` and `('a', 'bc')` differ.
- The nested assertions of an assertion are its children, recursively: a Merkle tree. An assertion's origin is not hashed (it is implied by where the digest is used), so anonymous assertions need no blank-node labelling.
- The result is `'sha256:'` and 64 hex digits.

**Normalization** is the merge of SPEC § Identity and graph merge: same-skeleton anonymous siblings collapse (with the interpretation compatibility condition: one-sided adoption, and a clash stays two claims), same-id assertions are one assertion. It is applied to a copy, so the graph passed in is never merged or otherwise changed, and a graph that is already merged is unaffected. A graph that breaks the identity rules (two assertions with one id and different skeletons) raises, as `merge()` does, rather than hashing.

**Nodes with nothing to say** (no types and no assertions, after exclusions) are omitted, from `node_digests` and from the graph digest. Such a node is only referenced: an edge named it, or a block declared it and said nothing. The two are the same content, and the second would otherwise differ across a store round trip.

**Subsets.** `nodes=` hashes only those nodes, with the same formula, so the digest of every node is the digest of that node whatever else is in the graph. A node that is not in the graph contributes what an empty one does: nothing.

## Exclusions

`onya:Document` nodes and `@source` assertions are excluded by default (`DEFAULT_EXCLUDE`). They record where text came from, not what it says; without this, splitting one file into three, each with its own `@document` and parser-added `@source`, would change the digest.

`exclude=` is a set of IRIs (full, CURIE, or `@` forms). A node with an excluded **type** is left out whole; an assertion with an excluded **label** is left out together with everything nested under it.

Passing `exclude=` **replaces** the default. To add to it, include the defaults: `exclude=DEFAULT_EXCLUDE | {...}`. `exclude=()` excludes nothing.

`@source` is excluded wherever it appears, so an author-written provenance `@source` is excluded too. The parser's document-source assertion and an authored one are the same term, and a graph doesn't remember which was which. Pass an `exclude` without `@source` if the provenance is meant to count.

## What changes the digest

Any value; interpretation (including gaining or losing one); type; edge target; assertion `@id`; `@ordering` (it is an ordinary nested property); any assertion's presence. What doesn't: the order of anything, prefixes, `@nodebase`, `@schema`, how the content was split across documents, merged versus unmerged, and a store round trip.

## Stability

The definition is versioned by this document: a change to it is a change to every digest, so it will not change within a release line. The digest string carries no version tag, in the style of `sha256:`; if the definition ever must change, the prefix will.
