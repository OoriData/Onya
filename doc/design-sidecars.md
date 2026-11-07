**Design document: Graph for concepts, sidecars for records**

A knowledge graph tends to collect anything anyone writes down: invoice amounts, sensor readings, the story of how a dispute was settled, a cached copy of a CRM record. Each addition looks harmless, but together they make the graph slower to load, more expensive to put in front of a model, harder to secure, and harder to reason over.

This pattern keeps the graph small and conceptual, and moves everything else into **sidecars**: plain tables or key/value stores that point back into the graph. The word is borrowed from sidecar files (the `.xmp` beside a photo, the `.onya` beside a `.csv`): data that travels alongside the main artifact without being part of it.

This is a usage pattern, not a change to the model: nothing here needs new Onya features. [The last section](#what-onya-provides) lists what `onya.circum` adds to make it easier to deploy (declared sidecars, a read-time view, and the write-side move). The examples use Onya Literate for the graph and Python dicts as the sidecar store. Swap in SQLite, PostgreSQL, Redis or anything else that persists; nothing depends on the backend. (The sidecar can even share a database with an [`onya.store`](design-persistence-architecture.md) backend, but it needn't, and the graph's tables shouldn't be where the rows go.)

## The test

> If someone would draw it on a whiteboard while explaining the business, it belongs in the graph. If they'd look it up in a spreadsheet, it belongs in a sidecar.

Put a fact in a sidecar when it:

- **accumulates** per event or period (readings, payments, timesheets);
- is **numeric detail** you compute over rather than reason about;
- needs **stricter access** than the rest of the graph (salaries, ownership);
- is **history or audit trail** (who decided what, and why);
- is a **cache** of a third-party system.

The graph keeps the entities, their relationships, rules, current state, and short pointers to where the detail lives.

## Before and after

A customer node that has picked up spreadsheet facts:

```
# acme [Organization <ex:Customer>]
* name: Acme Logistics
* <ex:status>: active, renewed in May after the pricing dispute
* <ex:fee>: $8,000/month retainer, capped at 40 hours
* <ex:resolution>: 2026-05-02 agreed to waive the June overage because of the outage
* description: Freight broker; we run their outbound sales. Started at $5,000/month.
```

The same node after the move:

```
# acme [Organization <ex:Customer>]
* name: Acme Logistics
* <ex:status>: active
  * <ex:note>: renewed in May after the pricing dispute
* <ex:feeModel>: retainer
* <ex:hoursCap>: true
* <ex:source>: decision log, 2026-05-02
* description: Freight broker; we run their outbound sales. Started at [amount on file]/month.
```

What changed:

- **The graph keeps the shape and the sidecar keeps the detail.** `feeModel: retainer` and `hoursCap: true` are enough to reason with ("which customers are on retainers?"). The verbatim fee goes to `billing_terms`.
- **Status becomes a closed set.** Free-text statuses such as "wrapping up", "dormant" or "not renewed" make every consumer write its own parser, and each one gets it slightly wrong. Keep the value to a small fixed vocabulary (`active | closed`) and move the prose into a nested `note`. This is the usual Onya move of keeping the value clean and the qualifier nested.
- **Narrative moves out and leaves a pointer.** The resolution goes to `decision_log`. The node keeps `source: decision log, 2026-05-02`, so a reader knows the fact was settled and where to find out how.
- **Figures in prose are redacted, not deleted.** The description still reads as a sentence. `[amount on file]` tells a reader, human or model, that the figure exists and lives elsewhere.

## Rows point at the graph by IRI

```python
from collections import defaultdict

# Each sidecar maps a subject IRI to its rows. Swap these dicts for a real store.
billing_terms: dict[str, list[dict]] = defaultdict(list)
decision_log: dict[str, list[dict]] = defaultdict(list)     # append-only
readings: dict[str, list[dict]] = defaultdict(list)

billing_terms['https://example.org/kg/acme'].append({
    'predicate': 'fee',
    'verbatim': '$8,000/month retainer, capped at 40 hours',
    'amount': 8000, 'unit': 'month', 'hours': 40,   # best-effort parse; the verbatim text is canonical
})
```

- **Use the full IRI, not a local slug.** Slugs collide across graphs, change when the node base changes, and can't be told apart from free text. If you start with slugs you'll end up migrating them.
- **Point at an assertion when the row is about one claim.** Give the claim an id (`* <ex:status>: active [=acme-status]`) and store that IRI in the row. Disputes and confidence scores attach to the claim, not the whole node. The transform below refuses to move an identified assertion for exactly this reason: a row somewhere may point at it.
- **The graph never points back per row.** A thousand readings mean a thousand rows, not a thousand edges. The graph's only reference to the sidecar is its catalog entry.

## Catalog every sidecar in the graph

An agent that reads only the graph can't use data it doesn't know exists. Give each sidecar one node, of type `@Sidecar`:

```
# billing-terms [@Sidecar]
* @label: Billing terms
* @system -> billing-db
* @table: billing_terms
* @sensitivity: internal
* @retention: life of the engagement plus seven years
```

That one node answers "do we track payments?" and "where?" from the graph alone. It's also the right place to record sensitivity and retention, because those are concepts, not data. Which properties a sidecar holds is not written on it: a property declares where its values live (`* @circumQuery -> billing-terms` on its `@Property`, see [design-circum.md](design-circum.md)), and `onya catalog` finds the properties that point at each sidecar. Rows are keyed by subject IRI, implicitly.

## Make the move a transform you can dry-run

Write the rules as one function that takes a graph and returns the rows, plus a list of anything it couldn't decide. (The simplest case is built in: once a property is declared as held in a sidecar, [`onya.circum.emit`](design-circum.md) moves its assertions out through a registered writer, with the same sidecar-first order and the same review list. The hard-coded `MOVE_OUT` below is what that replaces for labels you can name; a transform like this one remains the way to handle prose, redaction and status normalization.) The function edits the graph it's given, so a dry run is the same call on a copy, with the rows discarded.

```python
import re

from amara.iri import I

AMOUNT = re.compile(r'\$\s?\d[\d,]*(?:\.\d+)?k?', re.I)
MOVE_OUT = {'fee', 'invoicing'}         # leave the graph entirely
LEAVE_ALONE = {'conflict'}              # open disputes stay readable in the graph
STATUS = {'active': {'active', 'ongoing', 'live'}, 'closed': {'closed', 'ended', 'dormant', 'churned'}}


def local(iri) -> str:
    return re.split(r'[/#]', str(iri))[-1].lower()


def transform(g, ns: str, only: set | None = None) -> tuple[list[tuple[str, str, dict]], list[str]]:
    '''Rewrite g in place (pass a copy for a dry run). Return (sidecar, subject, row) triples and a review list.
    `only` limits the pass to those node ids; `ns` is the vocabulary base, e.g. 'https://example.org/vocab/'.'''
    rows, review = [], []
    for nid in list(g):
        if only is not None and nid not in only:
            continue
        node, subject = g[nid], str(nid)
        for prop in list(node.properties):
            pred, value = local(prop.label), prop.value or ''
            if pred in LEAVE_ALONE or not value:
                continue
            if (pred in MOVE_OUT or pred == 'resolution') and (prop.id or prop.properties or prop.edges):
                review.append(f'{local(nid)}: {pred} has an id or nested assertions; unchanged')
                continue  # removing it would take them along
            if pred in MOVE_OUT:
                rows.append(('billing_terms', subject, {'predicate': pred, 'verbatim': value}))
                node.remove_property(prop)
            elif pred == 'resolution':
                rows.append(('decision_log', subject, {'predicate': pred, 'verbatim': value}))
                node.remove_property(prop)
                node.add_property(I(f'{ns}source'), 'decision log')
            elif pred == 'status':
                word, _, rest = value.partition(',')
                term = next((t for t, words in STATUS.items() if word.strip().lower() in words), None)
                if term is None:
                    review.append(f'{local(nid)}: status {value!r} maps to no term; unchanged')
                    continue
                prop.value = term  # in place: nested assertions and the id stay attached
                if rest.strip():
                    prop.add_property(I(f'{ns}note'), rest.strip())
            elif AMOUNT.search(value):  # any other prose carrying a figure
                rows.append(('billing_terms', subject, {'predicate': pred, 'verbatim': value}))
                prop.value = AMOUNT.sub('[amount on file]', value)
    return rows, review
```

This sketch leaves out deriving `feeModel` and `hoursCap` from the fee text and stamping the date into `source`; both are a few more rules of the same kind.

For the dry run, a copy is a round trip. Onya guarantees `read(write(g))` equals `g`, so serializing and re-reading is a faithful copy (thread the original namespaces back so the copy reads like the original; see the [skill's note on `write`](../onya-graph.SKILL.md)):

```python
import io

from onya.serial.literate import read, write


def copy_of(g, parsed):  # parsed: the ParseResult g came from
    buf = io.StringIO()
    write(g, buf, document=parsed.doc_iri, schema=parsed.schema, nodebase=parsed.nodebase, prefixes=parsed.prefixes)
    return read(buf.getvalue()).graph
```

Some details:

- **Unclassifiable values go on a review list, not into a guess.** A rule that maps "paused pending budget" to `closed` is wrong in a way nobody will notice. A list of twenty items a person can clear in ten minutes is the better trade.
- **Leave some things alone on purpose.** An open conflict ("the contract says $6k, the invoice says $8k") is only useful if it's readable where people look, so it stays put, figures and all.
- **Rewrite in place; don't remove what carries structure.** Assigning `prop.value` keeps the property's nested qualifiers and id, so status normalization and redaction are safe. Moving a fact *out* removes it, and a removal takes nested qualifiers (which often mean something tied to their parent) and an `@id` (which a row or another edge may reference) with it. The transform flags those for review instead.
- **Make it idempotent.** Redacted text no longer matches `AMOUNT`, and a status that's already a closed-set term maps to itself, so a second pass finds nothing to do. Idempotence is what makes the next section safe.

## Run the rules on every write, not once

A one-off migration cleans the graph for about a week. People and agents keep writing the facts they know, and they know fees. Run the same `transform` over whatever nodes each write touched:

```python
SIDECARS = {'billing_terms': billing_terms, 'decision_log': decision_log}


async def apply_write(store, name, touched: set, ns: str) -> list[str]:
    g = await store.get(name)
    rows, review = transform(g, ns, only=touched)
    for table, subject, row in rows:                 # 1. sidecar first, so a crash loses nothing
        if row not in SIDECARS[table][subject]:      #    idempotent: a retry must not append twice
            SIDECARS[table][subject].append(row)
    await store.put(name, g, merge=False)            # 2. then replace the stored graph
    return review
```

The order is the important part. Write the sidecar rows, then remove the facts from the graph. Never make it possible for a fact to be in neither place. The cost of that ordering is that a crash between the steps leaves a fact in both places, which is why the append must be idempotent: the next pass finds the fact still in the graph, produces the same row, and skips it.

`merge=False` matters. `put` defaults to `merge=True`, which unions with what's stored, so a removed fact would come straight back. Replacing the whole graph also races with concurrent writers: serialize writes per graph, or for a large graph work on `store.subgraph(name, touched)` and apply the result with `store.remove`/`store.add`.

## Enforce access at the read tool

With dicts, or one database schema for everything, the store can't tell a partner from an intern. Put the check in the one typed function that reads each sidecar, and give the agent that function rather than raw query access:

```python
def get_compensation(subject: str, *, viewer) -> list[dict]:
    if not viewer.is_partner:
        raise PermissionError('compensation is partner-only')
    return list(compensation[subject])
```

The catalog node's `sensitivity` says who the tool should allow, and the tool enforces it.

## History: copy or move?

- **Move** a narrative out when the graph only needs the outcome. A resolution becomes a log row plus a `source` pointer.
- **Copy** it when the narrative is part of how people understand the entity. Keep a redacted `history` in the graph and log the verbatim original.
- **Keep the log append-only.** Correct a mistake by appending a new row, never by editing an old one. That's what makes the log trustworthy as an audit trail.

## A second example: readings

The same split applies far from billing:

```
# pump-7 [<ex:Pump>]
* name: Pump 7, north basin
* <ex:ratedFlow>: "120"
  * unitCode: "LTR"
  * <ex:per>: second
* <ex:status>: active
* <ex:feeds> -> basin-north

# basin-north [<ex:Basin>]
* name: North basin
```

```python
readings['https://example.org/kg/pump-7'].append({'at': '2026-10-08T09:00Z', 'flow': 114.2, 'temp_c': 41})
```

The rated flow is a spec, so it stays in the graph. Each measurement is an event, so it goes to the sidecar. If the pump fails, the graph changes status to `closed`, with a note and an `asOf` date. The readings that show why stay in the sidecar.

## What Onya provides

The pattern started as convention. `onya.circum` now covers the parts that were worth standardizing, and [design-circum.md](design-circum.md) is where they are specified:

1. **A catalog vocabulary.** `@Sidecar` (with `@label`, `@system`, `@table`, `@sensitivity`, `@retention`), `@System`, and `@circumQuery` / `@queryDetail` on a property. `onya catalog` lists sidecars and what they hold.
2. **A read-time view.** `augment` shows sidecar-held values in a new graph, marked with `@method` and `@asOf`; `strip` takes them out; a view is never persisted. Access is decided by the sidecar's `@sensitivity` and the application's policy, in the one place every read passes through.
3. **The write-side move.** `emit` hands a node's circum assertions to a writer and then removes them, sidecar first.
4. **An in-memory graph copy.** `graph.copy()` and `graph.subgraph(ids)` make dry runs and staged rewrites cheap.

Still convention: sidecar tables beside the graph in `onya.store`, so that "sidecar first, then graph" could be one transaction for small deployments.

## Summary

1. Whiteboard → graph; spreadsheet → sidecar.
2. Rows key on full IRIs (or assertion ids); the graph never points back per row.
3. One catalog node per sidecar, carrying sensitivity and retention.
4. Keep the shape in the graph (closed sets, flags, a redaction marker) and the detail in the sidecar.
5. Make the move an idempotent transform with a dry run and a review list.
6. Run it on every write, sidecar first, with an idempotent append.
7. Enforce access in the typed read tool.
8. Keep history append-only.
