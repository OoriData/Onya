# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.transient
'''
The do-not-persist marker. Some graphs are copies that must never be written back: a circum view
(`onya.circum.augment`) would make the graph swallow its sidecar, and a redacted graph
(`onya.redact.redact`) is missing what it withheld. Each says so in the graph itself, so the mark
survives being written out as text and read back, and a store's `put` refuses it:

    # chuks [Student]
    * @transient: true
        * @reason: redacted for a partner viewer

The mark is on each node that makes the copy unsafe, so a subgraph taken from it still carries it.
`@transient`'s value is `true`; `@reason` (text, nested) says why and may be repeated. Anything else
nested under it (a view's `@asOf` and `@method`) is the marking layer's own business.
'''

from onya.terms import ONYA_REASON, ONYA_TRANSIENT


class TransientError(ValueError):
    '''A graph carrying `@transient` marks was offered for persistence.'''


def mark(node, reason: str):
    '''Mark `node` as not to be persisted, for `reason`. Returns the `@transient` assertion, to nest more under it.'''
    for a in node.getprop(ONYA_TRANSIENT):
        if any(r.value == reason for r in a.getprop(ONYA_REASON)):
            return a  # already says so
    a = node.add_property(ONYA_TRANSIENT, 'true')
    a.add_property(ONYA_REASON, reason)
    return a


def transient(g) -> dict:
    '''`{node id: [reasons]}` for each node of `g` marked `@transient` (a mark with no reason gives `[]`).'''
    return {str(n.id): sorted({r.value for a in n.getprop(ONYA_TRANSIENT) for r in a.getprop(ONYA_REASON)})
            for n in g.nodes.values() if any(True for _ in n.getprop(ONYA_TRANSIENT))}


def check_persistable(g) -> None:
    '''Raise `TransientError`, naming the nodes and reasons, if any node of `g` is marked `@transient`.'''
    if found := transient(g):
        shown = '; '.join(f'{nid} ({", ".join(why) or "no reason given"})' for nid, why in list(found.items())[:3])
        raise TransientError(f'this graph is marked @transient and must not be persisted: {shown}'
                             f'{f" (and {len(found) - 3} more)" if len(found) > 3 else ""}')
