**Design document: the ordering layer**

The Onya core keeps the assertions of a node in **sets**, so the values of a label have no order. That is right for most knowledge: a person's emails, a company's offices. It is wrong for a few things where the sequence is the point: the address lines of a mapping, the authors of a paper, the steps of a procedure.

The ordering layer adds a sequence without changing the core. It defines two terms in the Onya core namespace (`onya:`), and says what they mean. It is a layer in the sense of SPEC § Reserved vocabulary: the terms are defined here, as additions to the core vocabulary, and how an implementation *without* this layer treats them is undefined. (A reader without the layer sees an ordinary nested property and a docheader line it can ignore, so nothing has to change for it to load the document.)

## The terms

| Term | Kind | Meaning |
|---|---|---|
| `@ordering` | nested property | An integer giving this occurrence's position among the occurrences of its label under the same parent. Smaller comes first. Gaps are fine (`10, 20, 30` leaves room to insert). |
| `@ordered` | docheader directive | Whitespace-separated labels whose occurrences get `@ordering` stamped from document order. |

`@ordering` is a plain nested property: it carries no interpretation, and nothing in the core model treats it specially. The layer's accessors read it as an integer, with the same grammar as `@as: integer` (`7`, `007`, `-3`, `1_000`; not `3.0`, not `1,000`).

## Writing it

By hand:

```markdown
# map-co-principalAddress [FieldMapping]
* sourceField: principaladdress2
  * @ordering: 2
* sourceField: principaladdress1
  * @ordering: 1
```

Or let the parser number them, from document order:

```markdown
# @docheader
* @schema: https://levver.io/regkg/
* @ordered: sourceField author

# map-co-principalAddress [FieldMapping]
* sourceField: principaladdress1
* sourceField: principaladdress2
* sourceField: principalcity
```

The stanza applies to the document that declares it. For each `(parent, label)` the n-th occurrence in the document is stamped `@ordering: n`, counting across all of a node's blocks in that document. It applies at every depth, to properties and edges alike. An `@ordering` the author wrote by hand is never overwritten, though the occurrence still counts, so the stamp is its *position*, not a count of the unstamped ones.

Stamps are numbered per document, so two documents that both stamp the same label under the same node reuse the same numbers. That is the same situation as a union conflict (below), and is dealt with the same way.

## Reading it

```python
n.ordered_values('sourceField')   # ['principaladdress1', 'principaladdress2', 'principalcity']
n.ordered_targets('author')       # nodes, in order
```

Both take the label forms `getprop` does. They are **strict**, deliberately: a label is either ordered, or it isn't.

- An occurrence with no `@ordering`, or one that isn't an integer, raises `OrderingError`. Returning "set order" for a half-stamped label would look ordered and not be.
- One claim carrying two different stamps, or two different claims sharing one, raises `OrderingConflict` (a subclass), naming both.
- Identical claims with the same stamp (the same line read twice, not yet merged) count once.
- A label with no values gives `[]`.

The accessor decides, not the docheader. The graph does not remember which labels were declared `@ordered`, so hand-written stamps work with no stanza, and a graph built through the API can be ordered the same way.

## Union stays generic

`union()` and `merge()` already combine nested assertions without understanding them, and they do not learn about `@ordering`. If two documents stamp the same claim differently:

```markdown
<!-- file a -->  * sourceField: principalcity
                   * @ordering: 3
<!-- file b -->  * sourceField: principalcity
                   * @ordering: 5
```

the claims have the same skeleton, so they merge into one assertion that carries both stamps. Nothing is lost and nothing is decided. `ordered_values` then raises `OrderingConflict`, and (once the shape layer exists) validation reports it as a finding.

Settling it is an explicit call:

```python
from onya.ordering import resolve

resolve(g, 'first')                          # keep the lowest stamp on each conflicted claim
resolve(g, 'last')                           # or the highest
resolve(g, lambda assertion, stamps: ...)    # your own rule: the claim and its sorted stamps -> the stamp to keep
```

It edits `g` in place and returns how many claims it changed. Two *different* claims left sharing a stamp are not a stamp conflict on either claim, and `resolve` does not touch them.

## Round trip

`write(g)` writes every stamp explicitly, and in order. That is faithful and verbose.

`write(g, ordered=r.ordered)` is the compact form. `ParseResult.ordered` carries the labels the document's stanza named, the way `r.prefixes` carries its prefixes. Given them, `write` emits the `@ordered` stanza, writes those labels' values in order, and leaves out stamps that are exactly `1..n` under their parent, since reading the stanza stamps them again. Anything the stanza couldn't reproduce stays explicit: gaps, a stamp with something nested under it (an `@source`, say), a label that is stamped only in part.

Either way `read(write(g))` preserves the order.

## A known limitation: repeated values

Repeating a claim under one label (`reading -> sicp` twice) merges into one assertion, because assertions are sets, so only one position survives. A list that genuinely repeats an entry needs an id for each occurrence:

```markdown
* reading -> sicp [=r1]
* reading -> htdp
* reading -> sicp [=r3]
```

The docheader stanza warns when it sees a repeated claim under a declared label, and names this remedy.

## Views

`onya.view` already ranks by a nested value (`order_by = "ex:priority"`). `order_by = "@ordering"` works the same way (comparing as integers, not text), and a field over a label whose every occurrence has a usable stamp follows it by default. If any occurrence is unstamped or in conflict, the label is an ordinary one again, because a view shows what is there and never rejects.

## What this layer does not do

It adds no ordering to the core, to `values()` and `targets()` (which stay sorted, for determinism), or to `union` and `merge`. It does not make a stamp mean anything outside its parent and label: there is no global order. It does not number across documents.
