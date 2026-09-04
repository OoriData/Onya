# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# demo/multi_extractor_provenance/multi_extractor_provenance_demo.py
'''
Demo: multiple extraction methods corroborating facts in one shared graph, tagged with the
reserved `@method`/`@confidence` provenance vocabulary (see SPEC: Optional assertion
provenance).

Three toy passes over one simulated 10-K filing write into the SAME shared graph, the way
a real pipeline (XBRL parser + document-structure parser + local NER/RE + LLM
cross-reference) would — no real external services, just enough of each pass's shape to
show the pattern:

- a deterministic pass (simulating an XBRL tag extractor): high confidence, exact.
- a mock "NER" pass (simulating a local GLiNER-Relex-style extractor over prose): lower
  confidence, corroborates the SAME fact the deterministic pass found.
- a mock "LLM cross-reference" pass: corroborates a DIFFERENT fact, one only it reaches.

Run from repo root:

    python demo/multi_extractor_provenance/multi_extractor_provenance_demo.py
'''

from amara.iri import I

from onya.graph import graph
from onya.terms import ONYA_METHOD_REL, ONYA_CONFIDENCE_REL, ONYA_INTERP
from onya.provenance import list_provenance, highest_confidence


FILING = I('http://example.org/filings/AcmeCorp10K')
REVENUE = I('https://schema.org/revenue')
RISK_FACTOR = I('https://schema.org/mentions')

XBRL_TAG_METHOD = I('https://example.org/methods/xbrl-tag')
NER_METHOD = I('https://example.org/methods/gliner-relex-ner')
LLM_CROSSREF_METHOD = I('https://example.org/methods/llm-crossref')

NUMBER = ONYA_INTERP('number')


def tag_assertion(assertion, g: graph, method: I, confidence: float | None = None):
    '''
    Shared helper standing in for what each pass's extraction code would call after
    asserting a fact: add a `@method` edge to a node identifying the method, and — for
    non-deterministic methods — a nested `@confidence`.
    '''
    method_edge = assertion.add_edge(ONYA_METHOD_REL, g.node(method) if method not in g else g[method])
    if confidence is not None:
        method_edge.add_property(ONYA_CONFIDENCE_REL, str(confidence), interp=NUMBER)
    return method_edge


def xbrl_pass(g: graph):
    '''Deterministic pass: reads a structured XBRL tag. Exact, so confidence is 1.0.'''
    filing = g.node(FILING) if FILING not in g else g[FILING]
    revenue = filing.add_property(REVENUE, '5323000000')
    tag_assertion(revenue, g, XBRL_TAG_METHOD, confidence=1.0)


def ner_pass(g: graph):
    '''Mock NER/RE pass: independently finds the SAME revenue figure in narrative prose.'''
    filing = g.node(FILING) if FILING not in g else g[FILING]
    revenue = filing.add_property(REVENUE, '5323000000')  # same skeleton -> merges with the XBRL one
    tag_assertion(revenue, g, NER_METHOD, confidence=0.87)


def llm_crossref_pass(g: graph):
    '''Mock LLM cross-reference pass: reaches a fact neither of the other two passes found.'''
    filing = g.node(FILING) if FILING not in g else g[FILING]
    mention = filing.add_property(RISK_FACTOR, 'supply chain concentration risk')
    tag_assertion(mention, g, LLM_CROSSREF_METHOD, confidence=0.72)


def main():
    g = graph()
    xbrl_pass(g)
    ner_pass(g)
    llm_crossref_pass(g)
    g.merge()  # collapse the two independently-asserted revenue properties into one

    filing = g[FILING]
    print(f'Filing {FILING} — {len(filing.properties)} distinct asserted properties\n')

    for prop in filing.properties:
        entries = list_provenance(prop)
        if not entries:
            continue
        print(f'{prop.label} = {prop.value!r}')
        for entry in entries:
            print(f'  - via {entry.method}  (confidence={entry.confidence})')
        best = highest_confidence(prop)
        if best is not None and len(entries) > 1:
            print(f'  -> highest_confidence(): {best.method} (confidence={best.confidence})')
        print()


if __name__ == '__main__':
    main()
