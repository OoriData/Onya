# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.redact
'''
Withhold what a viewer may not see. A `@Property` can say how sensitive its values are,

    # salary [@Property]
    * @sensitivity: partner

and `redact(g, viewer, policy)` returns a copy of `g` without the assertions of every label whose
sensitivity the policy refuses for that viewer. The policy is the one a circum `Registry` takes:
`policy(viewer, sensitivity)`, true to allow, so one function answers both "may this viewer read this
sidecar?" and "may this viewer see this property?".

A redacted graph is a **lossy copy**. Each node that lost something is marked `@transient` (see
`onya.transient`), so a store's `put` refuses it, and the mark survives being written out as text.

This is structural filtering of one graph, not a security boundary for everything the data touches: it
does not cover search over a store, edges into the graph from other graphs, or a digest of the original.
'''

from onya.shape import Shapes, load_shapes
from onya.transient import mark

REASON = 'redacted'  # deliberately says nothing about what was withheld, or why it was sensitive


def redact(g, viewer, policy, *, shapes=None):
    '''
    A new graph: `g` without the assertions (and everything nested under them) whose label is declared
    `@sensitivity` and which `policy(viewer, sensitivity)` refuses. `g` is not changed.

    policy -- `policy(viewer, sensitivity) -> bool`; required (None would mean "allow all", and then
        there is nothing to redact: don't call). Asked once per distinct sensitivity.
    shapes -- where the `@Property` declarations are: a graph or `Shapes`; by default `g` itself.

    A label is checked at every depth, so a sensitive label nested under an allowed assertion goes too.
    A node left with only its id and types stays, so edges to it don't dangle; every node that lost an
    assertion carries `@transient` with `@reason: redacted`. Nothing is inferred: a label no `@Property`
    declares, or one with no `@sensitivity`, is always allowed. Validate the original, not the copy:
    a withheld value will look missing.
    '''
    if policy is None:
        raise ValueError('redact needs a policy(viewer, sensitivity); None would allow everything')
    sh = shapes if isinstance(shapes, Shapes) else load_shapes(g if shapes is None else shapes)
    verdict: dict = {}  # sensitivity -> allowed?, so the policy is asked once per level

    def refused(label) -> bool:
        p = sh.properties.get(str(label))
        if p is None or p.sensitivity is None:
            return False
        if p.sensitivity not in verdict:
            verdict[p.sensitivity] = bool(policy(viewer, p.sensitivity))
        return not verdict[p.sensitivity]

    out = g.copy()

    def prune(container) -> bool:
        '''Remove refused assertions under `container`, at every depth; True if anything went.'''
        lost = False
        for a in [*container.properties, *container.edges]:
            if refused(a.label):
                (container.remove_edge if hasattr(a, 'target') else container.remove_property)(a)
                lost = True
            else:
                lost |= prune(a)
        return lost

    for n in out.nodes.values():
        if prune(n):
            mark(n, REASON)
    out.touch()
    return out
