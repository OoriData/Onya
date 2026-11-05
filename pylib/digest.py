# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.digest
'''
A canonical content digest: a hash of what a graph *says*, and nothing about how it was written.

Two graphs get the same digest exactly when they are equivalent (SPEC: Graph equivalence), however
they were split across files, ordered, prefixed or serialized, and whether or not their duplicate
assertions have been merged yet. Change any value, interpretation, type, edge target, assertion
`@id` or `@ordering` and the digest changes. The definition is in `doc/design-digest.md`.

    digest(g)                        # 'sha256:9f2c...'
    digest(g, nodes=[iri1, iri2])    # a subset, for incremental re-projection
    node_digests(g)                  # {iri: 'sha256:...'}: diff two versions cheaply

It is not the store's `skeleton_hash`, which is a merge-identity hash and leaves out `@id` and
interpretations on purpose.
'''

import hashlib

from onya.terms import ONYA_DOCUMENT, ONYA_SOURCE_REL

PREFIX = 'sha256:'

# What the digest leaves out unless told otherwise: the document nodes and the `@source` assertions
# the parser adds (`document_source_assertions`). They record where text came from, not what it says,
# so without this, splitting one file into three would change the digest. NB `@source` is excluded
# wherever it appears, an author-written provenance `@source` included.
DEFAULT_EXCLUDE = frozenset({ONYA_DOCUMENT, ONYA_SOURCE_REL})


def _hash(tag: str, *fields, children=()) -> bytes:
    '''
    SHA-256 over a tag, length-prefixed fields and a counted list of child digests. Length prefixes
    keep ('ab', 'c') and ('a', 'bc') apart; the child count does the same for the children.
    '''
    m = hashlib.sha256(tag.encode())
    for f in fields:
        b = f.encode('utf-8', 'surrogatepass')
        m.update(len(b).to_bytes(8, 'big'))
        m.update(b)
    m.update(len(children).to_bytes(8, 'big'))
    for c in sorted(children):  # sorted: the order of a set carries no meaning
        m.update(c)
    return m.digest()


def _assertion(a) -> bytes:
    '''H(kind, label, value-or-target-id, interp, id, sorted child digests). Merkle: no origin needed.'''
    is_edge = hasattr(a, 'target')
    payload = str(a.target.id) if is_edge else a.value
    kids = [_assertion(c) for c in (*a.properties, *a.edges)]
    return _hash('A', 'e' if is_edge else 'p', str(a.label), payload,
                 str(a.interp) if a.interp is not None else '', str(a.id) if a.id is not None else '',
                 children=kids)


def _node(n) -> bytes:
    '''H(id, sorted types, sorted assertion digests)'''
    kids = [_assertion(a) for a in (*n.properties, *n.edges)]
    return _hash('N', str(n.id), *sorted(map(str, n.types)), children=kids)


def _strip(container, labels: set) -> None:
    '''Drop assertions labelled with anything in `labels`, at every depth (their nested ones go too).'''
    for attr in ('properties', 'edges'):
        keep = {a for a in getattr(container, attr) if str(a.label) not in labels}
        setattr(container, attr, keep)
        for a in keep:
            _strip(a, labels)


def _normalized(g, nodes, exclude) -> dict:
    '''
    {node id: digest bytes} over the union-normalized content of `nodes` (all of `g` if None).
    Works on a copy, so `g` is untouched (and not merged by this).
    '''
    from onya.graph import _merge_container
    excluded = {str(g.resolve(x)) for x in exclude}
    wanted = set(g.nodes) if nodes is None else {g.resolve(x) for x in nodes} & set(g.nodes)
    wanted = {nid for nid in wanted if not excluded & {str(t) for t in g.nodes[nid].types}}
    work = g._extract(wanted)
    out = {}
    for nid in wanted:
        n = work.nodes[nid]
        _strip(n, excluded)
        _merge_container(n)  # SPEC Identity and graph merge; idempotent, so merged input is unaffected
        if n.types or n.properties or n.edges:  # an empty node says nothing: only referenced, never described
            out[nid] = _node(n)
    return out


def node_digests(g, *, nodes=None, exclude=DEFAULT_EXCLUDE) -> dict:
    '''
    `{node id: 'sha256:...'}` for each node that has content, sorted by id. Diff two versions of a
    graph by comparing these. A node with no types and no assertions (after exclusions) is left out:
    it is only referenced, and says nothing.
    '''
    found = _normalized(g, nodes, exclude)
    return {nid: PREFIX + found[nid].hex() for nid in sorted(found, key=str)}


def digest(g, *, nodes=None, exclude=DEFAULT_EXCLUDE) -> str:
    '''
    The content digest of `g`, `'sha256:<hex>'`; of just `nodes` (ids, CURIEs or bare names) when
    given. A node in `nodes` that isn't in `g` contributes nothing, as an empty node doesn't.

    `exclude` is a set of IRIs: a node with an excluded *type* is left out whole, and an assertion
    with an excluded *label* is left out with everything nested under it. Passing `exclude`
    **replaces** the default, so to add to it write `exclude=DEFAULT_EXCLUDE | {'ex:internalNote'}`;
    `exclude=()` excludes nothing (and then splitting a file across documents changes the digest).

    Raises (`AssertionIdConflict`, or `GraphMergeError` as `g.merge()` would) rather than hash a graph
    whose own identity rules are violated, e.g. two assertions sharing an `@id` but not a skeleton.
    '''
    found = _normalized(g, nodes, exclude)
    return PREFIX + _hash('G', children=list(found.values())).hex()
