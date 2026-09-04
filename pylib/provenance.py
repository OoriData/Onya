# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.provenance
'''
Accessors for the reserved `@method` / `@confidence` provenance vocabulary (see SPEC §
Optional assertion provenance).

Multiple methods (a deterministic parser, a local NER/RE pass, an LLM cross-reference
step, ...) can corroborate the same fact within one shared graph. Onya reserves `@method`
(an edge to a node identifying the method) and `@confidence` (a property nested *under*
that edge, not a sibling of it — nesting keeps each corroborating method's confidence
self-contained, so merge never conflates one method's confidence with another's) so this
is discoverable across projects rather than reinvented per pipeline.

Like the interpretation layer, this module honors the vocabulary on demand and never
mutates the graph: `list_provenance` reads every corroborating entry, and
`highest_confidence` is a read-time *view*, not a merge policy. Onya asserts no canonical
confidence scale or cross-method comparability — the caller decides what a 0.83 means.

Nothing in the core model or the parser imports this module. `@method`/`@confidence` are
caller-authored (unlike the parser-generated `@source`); they are ordinary reserved-vocabulary
assertions, authorable directly in Onya Literate or via `add_edge`/`add_property`.
'''

from __future__ import annotations

from dataclasses import dataclass

from onya.graph import edge
from onya.terms import ONYA_METHOD_REL, ONYA_CONFIDENCE_REL


__all__ = ['ProvenanceEntry', 'list_provenance', 'highest_confidence']


@dataclass(frozen=True)
class ProvenanceEntry:
    '''One corroborating `@method` entry on an assertion, with its own nested `@confidence`.'''
    method: str | None       # str(target id) of the @method edge; None if the target is unresolved
    confidence: float | None  # parsed from the nested @confidence property; None if absent/unparseable
    assertion: edge           # the @method edge itself, for further traversal (e.g. method metadata)


def _confidence_of(method_edge: edge) -> float | None:
    for prop in method_edge.getprop(ONYA_CONFIDENCE_REL):
        try:
            return float(prop.value)
        except ValueError:
            return None
    return None


def list_provenance(assertion) -> list[ProvenanceEntry]:
    '''
    Every corroborating `@method` entry on `assertion` (a node, property, or edge), each
    carrying its own `@confidence` where present. Returns `[]` when there is no provenance
    tagging at all — this is a query over ordinary vocabulary, not a required annotation.
    '''
    entries = []
    for method_edge in assertion.getedge(ONYA_METHOD_REL):
        target = method_edge.target
        method = str(target.id) if target is not None and getattr(target, 'id', None) is not None else None
        entries.append(ProvenanceEntry(method=method, confidence=_confidence_of(method_edge), assertion=method_edge))
    return entries


def highest_confidence(assertion) -> ProvenanceEntry | None:
    '''
    Read-time opt-in "pick the best" view over `list_provenance(assertion)`: the entry
    with the highest `confidence`, or `None` when there are no entries or none carry a
    parseable confidence. Never mutates the graph — corroborating entries are never
    collapsed away; this is a view a caller reaches for on demand.
    '''
    scored = [e for e in list_provenance(assertion) if e.confidence is not None]
    if not scored:
        return None
    return max(scored, key=lambda e: e.confidence)
