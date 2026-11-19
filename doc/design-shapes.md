**Design document: the shape layer**

Shapes say what a graph is *expected* to look like, and `onya.shape.validate()` reports where it isn't. They are lightweight and RDFS-flavored, written as ordinary Onya nodes in the core namespace (`onya:`), so there is no `rdf:` versus `rdfs:` to remember. Like data contracts they are optional: a graph with no shapes is unaffected, and a graph that breaks its shapes is still valid Onya.

It is a layer in the sense of SPEC § Reserved vocabulary. The terms below are defined here, as additions to the core vocabulary. An implementation without the layer sees ordinary nodes, types and assertions, and what it does with them is undefined (it must not reject the document).

## Rules the layer keeps

| Experience with RDFS and SHACL | Shape rule |
|---|---|
| `rdfs:domain` / `rdfs:range` **infer** types, which surprises everyone | Shapes **never infer and never mutate**. They only report. |
| Multiple domains and ranges are conjunctive in RDFS, so schema.org invented `domainIncludes` / `rangeIncludes` | `@appliesTo` and `@range` are **any-of** by definition. |
| RDFS has no cardinality; SHACL adds `minCount` / `maxCount` | `@cardinality` is first-class. |
| An open world surprises people who wanted a schema | **Open by default**; `@closed: true` on a class opts in to "undeclared labels are findings". |
| SHACL has severity levels | Findings carry a `severity`: `error` by default, `@severity: warning` on a declaration. |
| Enumerations as a class hack | `@oneOf` lists the allowed values of a property. |
| Subclassing for validation, not for entailment | `@subClassOf` is closed over **at validation time only**. |

## Vocabulary

```
# Person [@Class]
* @label: Person

# Student [@Class]
* @subClassOf -> Person

# name [@Property]
* @appliesTo -> Person
* @as: text
* @cardinality: 1

# knows [@Property]
* @appliesTo -> Person
* @range -> Person

# status [@Property]
* @appliesTo -> Student
* @oneOf: active
* @oneOf: closed
* @cardinality: 1
```

| Term | On | Meaning |
|---|---|---|
| `@Class`, `@Property` | type | Declares a class, or a property (the node's id is the label IRI it declares). |
| `@label` | either | A human-readable name. Documentation only. |
| `@subClassOf -> C` | class | Instances of this class are also instances of `C`, for validation. |
| `@closed: true` | class | A node of this class using a label no declaration covers is a finding. |
| `@appliesTo -> C` | property | The property is for nodes of these classes (any of). Omitted: any node. |
| `@range -> C` | property | The property is an **edge**, to a node of one of these classes (any of). |
| `@as: interp` | property | The property is a **value** read as this interpretation. A default, as with `@interpretations`. |
| `@oneOf: v` | property | An allowed value; repeat for each. Their order is [the author's, if stamped](#the-order-of-a-declarations-lists). |
| `@cardinality: m` | property | How many distinct values or targets a node has: `1`, `0..1`, `1..*`, `0..*`, `*` (= `0..*`) or `n..m`. |
| `@ordered: true` | property | The label's values are ordered, and validation checks the `@ordering` stamps (the [ordering layer](design-ordering.md)). |
| `@severity: s` | either | `error` (default) or `warning`: the severity of findings the declaration produces. |
| `@deprecated: text` | either | The class or label is deprecated; the text is the guidance (what to use instead, and why). |
| `@replacedBy -> X` | either | What supersedes it: a `@Class` or `@Property` (repeat for several). On its own, it also marks the declaration deprecated. |
| `@sensitivity: level` | property | How sensitive its values are: a string from the application's own vocabulary (`partner`, `clinical`). Nothing in validation reads it; [`redact`](#withholding-sensitive-properties-redact) asks a policy about it. The same term the circum layer puts on a `@Sidecar`. |

Other layers add terms to the same declarations. The circum layer reads `@circumQuery` (the values are held in a sidecar), `@qualifier` and `@attribute` (nested labels that tell a property's values apart, or ride along), and `@table` / `@column` (names); see [design-circum.md](design-circum.md). Shapes themselves ignore them.

**One `@Property` for values and edges.** `@range` makes it an edge; `@as` or `@oneOf` make it a value; declaring both is a malformed declaration. That follows Onya's property/edge duality and avoids a class explosion of property kinds.

**`@as` replaces `@range -> @text`.** A range naming an interpretation would resolve to `onya:text`, not `onya:interp/text`, which is a trap. `@as` already means "read as". A property's `@as` is a *default* for that label: an assertion's own `@as` wins, and is checked as always. (At the top level of a node, `@as` has nothing to annotate, so the parser keeps it as a property holding the resolved interpretation IRI; `write` prints it back as `@as: integer`.)

**One `@cardinality`, not `@cardinality` plus `@required`.** A boolean beside a multiplicity can contradict itself. Identical values count once, as they would after a merge. A minimum is enforced on every node of the class, including one that doesn't use the label at all; a property with no `@appliesTo` only has its maximum checked.

**Ordering.** `@ordered: true` makes missing, non-integer and conflicting stamps findings. It does *not* number anything: parsing never reads shapes, so stamps still come from the docheader's `@ordered` stanza or by hand.

## Nested assertions

Onya labels mean one thing wherever they appear, so a declared property's value checks hold when its label is nested under another assertion:

```
# role [@Property]
* @range -> Role              # a nested `role` must target a Role, as a node's own would

# roleName [@Property]
* @oneOf: lead
* @oneOf: member
```

```
# ada [Person]
* assigned: team
    * role -> editor          # checked: editor must be a Role
    * roleName: boss          # a `one_of` finding: 'boss' is not one of ['lead', 'member']
```

- **What is checked nested:** `@range` and `@oneOf` (findings `range` and `one_of`, with `nested under <parent label>: ` at the start of `detail`, the offending line, and the node whose assertion holds it), and deprecation (above). An assertion's own `@as` was already checked at every depth. A declaration's *default* `@as` still applies only to a node's own values.
- **What is not:** `@appliesTo` and `@cardinality` speak of a node and its class, and a nested assertion has neither, so they stay with a node's own assertions. A property declared `@appliesTo -> Person` with `@cardinality: 1` is still required on each Person node, and a nested use of it neither satisfies nor breaks that. For a label that is only ever nested, declare it without them.
- **Not supported:** a declaration that depends on its parent (`role` is a Role only under `assigned`, and something else under `owner`). A label has one declaration. If you need context-dependent shapes, give the labels different names.

## Deprecating a term

A class or property that should no longer be used says so, with the guidance a person needs, so the guidance lives with the declaration instead of in a table beside it:

```
# nickname [@Property]
* @appliesTo -> Person
* @deprecated: Use preferredName instead; nickname loses the language.
* @replacedBy -> preferredName
```

`validate` then gives each node that uses `nickname` one `deprecated` finding (however many values it has), and each node *typed* with a deprecated class likewise:

```
warning deprecated: http://e.o/ada http://e.o/nickname: label http://e.o/nickname is deprecated: Use preferredName instead; nickname loses the language. Replaced by http://e.o/preferredName. (at ...)
```

- It is always a **warning**, whatever `@severity` says: `@severity` is how serious the declaration's other findings are, and a term that is merely going away isn't an error. `onya validate` prints it with the other warnings, and `--strict` makes it fail the run.
- Either term marks the declaration deprecated, so `@replacedBy` alone is enough, and `@deprecated` alone is too. More than one `@deprecated` is a `bad_shape`.
- A subclass of a deprecated class is not itself deprecated: only nodes typed with the class are reported. Deprecating a subclass is the subclass's own declaration.
- Nothing is changed or inferred: the deprecated term keeps validating exactly as before, and `@replacedBy` isn't checked to exist (a forward reference is normal in an open graph). A deprecated label is reported wherever it is used, nested under an assertion included (one finding per node per label, the node's own use first; a nested one says `nested under <label>:` in its `detail`).
- `Shapes` exposes it as `deprecated` (the guidance, `''` if only `@replacedBy` was given, `None` if not deprecated) and `replaced_by` on `PropertyShape` and `ClassShape`.

## Withholding sensitive properties: `redact`

A property can say how sensitive its values are, and a viewer-based filter can withhold them while they stay in the graph (a staged migration, or one graph served to several audiences):

```
# salary [@Property]
* @appliesTo -> Person
* @sensitivity: partner
```

```python
from onya.redact import redact

policy = lambda viewer, sensitivity: viewer.is_partner or sensitivity == 'public'   # true to allow
shown = redact(g, viewer, policy)         # a new graph; shapes from g, or pass shapes=
```

The policy has the signature of a circum `Registry`'s, so one function answers "may this viewer read this sidecar?" and "may this viewer see this property?". `redact` asks it once per distinct `@sensitivity`, and returns a **new graph** (`g` is untouched):

- Every assertion whose label is declared `@sensitivity` and refused is gone, with everything nested under it, at any depth: a sensitive label nested under an allowed value goes too. A label no `@Property` declares, or with no `@sensitivity`, is always kept.
- A node left with only its id and types stays, so edges to it don't dangle.
- **The copy is lossy, so it is marked.** Each node that lost an assertion gets `@transient` with `@reason: redacted`, and a store's `put` refuses it (see [the SPEC](../SPEC.md#do-not-persist-marker-transient-reason)). The mark says nothing about what was withheld, but it does say that something was: a viewer can tell a node was redacted.
- **Validate the original.** A withheld value will look missing in the copy.
- **The declarations stay in the copy**, `@sensitivity` included, since a viewer needs them to read the graph. If the schema itself is confidential, redact a graph that holds only the data, with `shapes=` given separately.
- **Not a security boundary for everything.** `redact` filters one graph in memory. It does not cover search over a store, edges into the graph from other graphs, or a digest of the original. A property held in a sidecar is decided by the sidecar's own `@sensitivity` and the registry's policy, not here.

## Where declarations live, and what they match

A declaration's node id is the IRI it declares, so a `@Class` node's id is the class IRI, and a `@Property` node's id is the label IRI. Instances name classes through `[Type]` (under `@typebase`/`@schema`) and labels through `@schema`, while a node header is written under `@nodebase`. Declarations therefore line up when `@nodebase` and `@schema` are the same, as in the examples here, or when the headers are written as CURIEs or full IRIs. Nothing guesses: a declaration for an IRI nothing uses simply never fires.

Shapes may be in the graph being validated, in a separate graph (`validate(data, shapes=shapes_graph)`), or precompiled (`load_shapes(g)` gives a `Shapes`, whose `classes` and `properties` the tables layer reads for column types).

## Findings

```python
from onya.shape import validate

report = validate(g, shapes=g)            # or validate(g), shapes in the graph itself
for f in report.findings:
    print(f.severity, f.kind, f.node, f.label, f.detail, f.location)
```

| kind | example |
|---|---|
| `applies_to` | `jobTitle` used on a node that is only an `Org` |
| `cardinality` | `name` has 2 values, declared `1` (or has none) |
| `range` | `knows` target `acme` is not a `Person` (subclass-closed), or an edge where a value is declared, or the reverse |
| `one_of` | `status: dormant`, not in `{active, closed}` |
| `as` | `age: "a year"` fails `@as: integer`; also an assertion's own `@as`, at any depth |
| `ordering` | a missing, non-integer or conflicting `@ordering` on an `@ordered: true` label |
| `undeclared_label` | on a node of a `@closed: true` class |
| `deprecated` | a node uses a `@deprecated` label, or is typed with a `@deprecated` class (always a *warning*) |
| `unknown_reserved_term` | `@Calss` (a *warning*) |
| `dangling` | an edge target nothing declares (with `dangling=True`; `allow=` for external IRIs) |
| `bad_shape` | a declaration that can't be read: `@cardinality: lots`, `@severity: loud` |

`Report` has `findings`, `ok`, `errors` and `warnings`. Findings are data: validation never raises for one, never runs implicitly, and never changes parsing. They carry a `location` when the read tracked locations (the CLI always does). Nodes typed `@Class`, `@Property` or `@Document` are declarations, not data, and are not checked. A node's own assertions meet all of a declaration; assertions nested under them are checked too, as described under [Nested assertions](#nested-assertions).

## Validating a change: `against=`

A proposed change is often a *fragment*: a few nodes, with no declarations and none of the targets they point at. Alone, every target looks untyped (`range` findings), and a value added to a node that already has one never meets its `@cardinality`. `against` checks the fragment as if it were merged into a base graph:

```python
frag = read(proposed).graph                  # `ify knows -> chuks`, and nothing else
report = validate(frag, against=base)        # shapes from the base, unless shapes= is given
```

- **Types resolve through the base.** `chuks` is a `Student` in the base, so `knows -> chuks` satisfies `@range -> Person`; a target that is an `Org` there does not.
- **Cardinality counts the base's values.** A fragment giving `chuks` a second `name`, when `name` is `@cardinality: 1`, is a finding. A fragment that gives `chuks` nothing a Student requires is not: the base already holds it.
- **Only the fragment's own nodes are reported.** A node the fragment names, whether new or already in the base, is checked on its merged assertions. The base's problems on other nodes, including neighbors that were copied in only to resolve a type, are never reported.
- **The cost follows the fragment.** Only the nodes the fragment names, its edge targets, and their neighbors are copied from the base (`graph.subgraph`), never the whole base. Pass a loaded `Shapes` (`load_shapes(base)`) when checking many fragments, so the declarations are read once.
- **Neither graph changes.** A fragment that can't merge into the base (the same assertion `@id` with different content) raises `GraphMergeError`, as a `put` would. A finding names no line, since it is about the merged copy.

Only additions can be expressed in a fragment, so there is nothing to check for a removal.

**A base in a store.** `validate` is synchronous, so a stored base has its own coroutine, with the same rules:

```python
from onya.shape import validate_against_store

report = await validate_against_store(frag, store, ['http://e.o/authored', 'http://e.o/runtime'])
```

On SQLite and PostgreSQL only the neighborhood the fragment touches is read (`subgraph`, or `subgraph_across` for several graphs), and, when `shapes=` isn't given, only the stored `@Class` and `@Property` nodes, so the base is never loaded whole. A name with no graph yet (a runtime graph nothing has written to) is skipped. The file store has no `subgraph`, so it reads each named graph: correct, but not bounded by the fragment.

**On the command line**, `--against=FILESPEC` takes the base as files, and `--store=URL --graph=NAME[,NAME]` as a store:

```
onya validate proposed.onya --against=kg/
onya validate proposed.onya --store=sqlite:kg.db --graph=http://example.org/kg
```

## The order of a declaration's lists

The graph keeps assertions in sets, so `@oneOf`, `@qualifier`, `@attribute` and `@replacedBy` have no order of their own. When the order matters (a lifecycle `lead / active / closed`, the columns of a ledger's key), ask for it with the [ordering layer](design-ordering.md): list the labels in the shapes file's docheader and the parser stamps them from document order.

```
# @docheader
* @ordered: @oneOf @qualifier @attribute @replacedBy

# status [@Property]
* @oneOf: lead
* @oneOf: active
* @oneOf: closed
```

`PropertyShape.one_of`, `.qualifiers`, `.attributes` and `.replaced_by` are then tuples in that order (`('lead', 'active', 'closed')`), and `one_of` findings list the values in it. Without stamps the order is **sorted**: stable from run to run, but not the order written. A half-stamped list, or stamps that clash, give a `bad_shape` finding and sorted order. A ledger's key columns follow `@qualifier`'s order, so stamp it if the order of the key matters to you. (Before 0.7.1 these tuples came out in an arbitrary order: a set's.)

## Taking inventory of an open world

Shapes are open, so a graph can use labels and types nobody declared, and `validate` stays quiet about them (an `undeclared_label` finding exists only for a class marked `@closed`). A periodic audit wants the opposite question: what is in use that nothing covers, and what is declared that nothing uses? That is not a violation, so it is a function and not a finding kind:

```python
from onya.shape import inventory

inv = inventory(g, shapes=None, examples=3)   # shapes: a graph or Shapes; None means g itself
inv.labels             # {label IRI: Entry(count, nodes, examples)}, node-level labels no @Property declares
inv.types              # {type IRI: Entry(...)}, types no @Class declares
inv.nested_labels      # {label IRI: Entry(...)}, undeclared labels nested under another assertion
inv.declared_unused    # {'labels': [...], 'types': [...]}: declared, and nothing uses them
```

```
$ onya inventory kg/ --shapes=shapes/
undeclared labels:
       7  http://e.o/nick  (3 nodes)
          e.g. http://e.o/al Alfie
          e.g. http://e.o/al Ally
          e.g. http://e.o/bo B
       1  http://e.o/tattoo  (1 node)
          e.g. http://e.o/al none
declared but unused types:
  http://e.o/Spare
```

- **Counts.** `count` is the number of assertions using a label (for a type, the number of nodes typed with it); `nodes` is how many distinct nodes hold it (for a nested label, the node the assertion hangs from). `examples` are `(node id, value or target)` pairs, the first ones in node-id order.
- **Stable.** Each table runs from most used to least, ties by IRI, and examples are sorted, so two runs over the same graph print the same text and the output diffs from week to week.
- **What counts as declared.** A label is covered if any `@Property` declares it, whatever it applies to (a label on the wrong class is an `applies_to` finding, not an undeclared label), or, when nested, if some property lists it as a `@qualifier` or `@attribute`. A closed class's labels are inventoried too: `@closed` changes what `validate` reports, not what is in the graph.
- **Not inventoried.** Reserved `@` terms, and nodes typed `@Class`, `@Property` or `@Document`, as `validate` does not check them either.
- **Unused.** A class is used when some node's type is it or a subclass of it, so an abstract parent with only subclass instances is not reported. A label counts at any depth. A label held in a sidecar (`@circumQuery`) is never reported unused: its values aren't in the graph to find.
- **Declared labels: `uses`.** `inventory` is about what is undeclared. For where *declared* labels are used (the nested ones included), `uses(g, shapes, where=pred, examples=3)` returns the same entries, node-level in `.labels` and nested in `.nested_labels`, for the labels whose `PropertyShape` the predicate accepts (none: all). It tests anything a shape carries, so there is no vocabulary of filters: `uses(g, where=lambda p: p.sensitivity)` is where sensitive data is held, `uses(g, where=lambda p: p.deprecated is not None)` is what still uses a deprecated term. It has no CLI form.
- **Exit status.** `onya inventory` always exits 0 unless the input does not parse; it audits, it does not check. `--examples=0` omits the instances.

## The command line

```
onya validate kg/                                    # shapes in the same files
onya validate kg/ --shapes=shapes/ --dangling --allow=https://orcid.org/ --strict
onya inventory kg/ --shapes=shapes/                  # what is used but undeclared, and the reverse
```

Exit status of `validate` is 2 when there are error findings (with `--strict`, warnings too) and 0 otherwise.

## Migrating from other vocabularies

Shapes deliberately read only their own terms. They do **not** treat `rdfs:subClassOf`, schema.org's `domainIncludes` / `rangeIncludes`, or a project's own `appliesTo` / `cardinality` as aliases: migration is an explicit, coded transform you run once and can review, not a silent reinterpretation in the heart of Onya. Such a transform is a small script over the graph (read the old terms, write `@Class` / `@Property` nodes); schema.org-to-Onya scripts are a natural companion project.

## Mapping to SHACL

For readers who know SHACL. This is documentation, not an implementation: no SHACL is read or written.

| Onya | SHACL |
|---|---|
| `@Class` node | `sh:NodeShape` with `sh:targetClass` |
| `@subClassOf` | `rdfs:subClassOf` (SHACL targets follow it as well) |
| `@Property` + `@appliesTo -> C` | a `sh:property` shape on the node shape for `C` (`sh:path` = the property) |
| `@range -> C` | `sh:class C` (with `sh:nodeKind sh:IRI`) |
| `@as: integer` | `sh:datatype xsd:integer` (value kind and checking are by interpretation) |
| `@oneOf: v` (repeated) | `sh:in (v ...)` |
| `@cardinality: n..m` | `sh:minCount n` / `sh:maxCount m` |
| `@closed: true` | `sh:closed true` |
| `@severity: warning` | `sh:severity sh:Warning` |
| any-of `@appliesTo` / `@range` | `sh:or` |
| (no equivalent) | SHACL's `sh:pattern`, `sh:node`, `sh:sparql` and the rest of its constraint language |
| `@ordered` | (no equivalent: SHACL has no ordering of values) |

The differences are the point: no inference, open by default, and any-of as the only way to list classes.
