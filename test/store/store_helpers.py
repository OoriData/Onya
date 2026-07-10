# -*- coding: utf-8 -*-
# test/store/store_helpers.py
'''
Shared helpers for the store conformance suite: parsing, in-memory graph reference (the
model union every backend is measured against), and a structural equality check that
compares property values by string content (LITERAL vs str is a Python-type distinction,
not a value one — the existing serializer tests normalize it the same way).
'''

from onya.graph import edge, graph
from onya.serial.literate import LiterateParser
from onya import LITERAL


DOCHEADER = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/
'''

NAME = 'http://e.o/doc'


def parse(text: str) -> graph:
    '''Parse one Onya Literate string into a fresh graph (no merge).'''
    g = graph()
    LiterateParser().parse(text, g)
    return g


def reference(*docs: str) -> graph:
    '''The in-memory union of the given docs — the semantics every backend must reproduce.'''
    g = parse(docs[0])
    for d in docs[1:]:
        g.union(parse(d))
    return g


def _pv(v):
    return str(v) if isinstance(v, LITERAL) else v


def canon(g: graph) -> dict:
    '''A hashable structural signature of a graph, order-independent, for equality asserts.'''
    def asig(a):
        kind = 'E' if isinstance(a, edge) else 'P'
        payload = str(a.target.id) if isinstance(a, edge) else _pv(a.value)
        kids = sorted([asig(x) for x in a.properties] + [asig(y) for y in a.edges], key=repr)
        return (kind, str(a.label), payload,
                str(a.id) if a.id is not None else None,
                str(a.interp) if a.interp is not None else None,
                tuple(kids))
    out = {}
    for nid, n in g.nodes.items():
        assertions = sorted([asig(a) for a in n.properties] + [asig(a) for a in n.edges], key=repr)
        out[str(nid)] = (tuple(sorted(str(t) for t in n.types)), tuple(assertions))
    return out


def same(a: graph, b: graph) -> bool:
    return canon(a) == canon(b)
