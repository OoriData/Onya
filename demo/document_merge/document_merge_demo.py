# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# demo/document_merge/document_merge_demo.py
'''
Demo: parsing multiple documents into one graph.

This demonstrates the recommended 'merge' workflow:
- parse each document into a shared graph
- (optionally) enable assertion provenance via @source tagging

Run from repo root:

    python demo/document_merge/document_merge_demo.py
'''

from pathlib import Path

from onya.graph import graph
from onya.serial.literate_lex import LiterateParser
from onya import ONYA_BASEIRI


def main():
    root = Path(__file__).resolve().parents[2]

    docs = [
        root / 'test' / 'resource' / 'schemaorg' / 'thingsfallapart.onya',
        root / 'test' / 'resource' / 'schemaorg' / 'achebe-bio.onya',
    ]

    g = graph()
    op = LiterateParser(document_source_assertions=True)

    for p in docs:
        text = p.read_text(encoding='utf-8')
        result = op.parse(text, g)
        print(f'Parsed {p.name}: @document={result.doc_iri!r}, nodes_added={len(result.nodes_added)}')

    print(f'\nMerged graph node count: {len(g)}')

    # Show how provenance appears as an assertion sub-property
    source_rel = ONYA_BASEIRI('source')
    example_node = 'http://example.org/classics/TFA'
    if example_node in g:
        print(f'\nAssertions for {example_node} (showing @source if present):')
        for o, rel, t, ann in g.match(example_node):
            src = ann.get(source_rel)
            rel_s = str(rel)
            print(f'- {rel_s} -> {t!r}' + (f'  (@source={src})' if src else ''))


if __name__ == '__main__':
    main()
