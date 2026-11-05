# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.ordering
'''
The ordering layer: a way to say that the values of a label come in a sequence.

The core model keeps assertions in sets, so a label's values have no order. This layer adds one
without changing the core: each occurrence carries a reserved nested property `@ordering` (an
integer; gaps are fine), and `node.ordered_values(label)` / `node.ordered_targets(label)` read the
occurrences back in that order. In Onya Literate a docheader stanza stamps the numbers from document
order, so authors needn't number by hand:

    * @ordered: sourceField author

`@ordering` and `@ordered` are defined by this layer, as additions to the Onya core vocabulary; see
`doc/design-ordering.md`. A reader without the layer sees an ordinary nested property and a
docheader line it can ignore, which is why nothing here makes the core reject or reinterpret them.

Union stays generic: two documents that stamp the same claim differently simply leave two stamps on
it. The accessors raise `OrderingConflict` rather than pick one, and `resolve()` is the explicit,
policy-driven fixup.
'''

from collections.abc import Callable

from onya.interp import _INTEGER_RE
from onya.terms import ONYA_ORDERING


class OrderingError(ValueError):
    '''
    Raised by `ordered_values()` / `ordered_targets()` when the stamps can't give a sequence: an
    occurrence has no `@ordering`, or one that isn't an integer. Carries `origin` (the node or
    assertion asked), `label` (resolved) and `problem` (what was wrong, naming the occurrence).
    '''
    def __init__(self, origin, label, problem: str):
        self.origin, self.label, self.problem = origin, label, problem
        who = getattr(origin, 'id', None) or origin
        super().__init__(f'{who}: cannot order {label}: {problem}')


class OrderingConflict(OrderingError):
    '''
    Stamps that disagree: one claim stamped with two different numbers (typically two documents that
    were unioned), or two different claims given the same number. Fix with `resolve()`, or edit.
    '''


def stamp_int(value: str) -> int | None:
    '''A stamp's integer value, or None when it isn't one (the same grammar as `@as: integer`).'''
    return int(value.replace('_', '')) if _INTEGER_RE.match(value) else None


def stamps(a) -> list:
    '''The `@ordering` properties nested directly under assertion `a`.'''
    return [p for p in a.properties if p.label == ONYA_ORDERING]


def stamp_of(a) -> int | None:
    '''`a`'s position, or None if it has no stamp, a non-integer one, or conflicting ones.'''
    found = {stamp_int(p.value) for p in stamps(a)}
    return found.pop() if len(found) == 1 and None not in found else None


def _claim(a) -> str:
    '''Short description of an occurrence, for messages.'''
    return f'-> {a.target.id}' if hasattr(a, 'target') else repr(a.value)


def _identity(a):
    '''What makes two occurrences the same claim: the value, or the target.'''
    return ('e', str(a.target.id)) if hasattr(a, 'target') else ('p', a.value)


def ordered(origin, label, found) -> list:
    '''
    The assertions in `found` (all of one label, on `origin`) in `@ordering` order.

    Strict by design: an occurrence with no stamp is an error, not "set order", so a half-stamped
    label never looks ordered. Identical claims with the same stamp (not yet merged) count once.
    '''
    keyed = []
    for a in found:
        nums = {}
        for p in stamps(a):
            n = stamp_int(p.value)
            if n is None:
                raise OrderingError(origin, label, f'{_claim(a)} has @ordering {p.value!r}, which is not an integer')
            nums[n] = p.value
        if not nums:
            raise OrderingError(origin, label, f'{_claim(a)} has no @ordering')
        if len(nums) > 1:
            raise OrderingConflict(origin, label, f'{_claim(a)} has conflicting @ordering values {sorted(nums)}')
        keyed.append((next(iter(nums)), a))
    keyed.sort(key=lambda t: t[0])
    out, last = [], None
    for n, a in keyed:
        if last is not None and last[0] == n:
            if _identity(last[1]) != _identity(a):
                raise OrderingConflict(origin, label, f'{_claim(last[1])} and {_claim(a)} share @ordering {n}')
            continue  # the same claim twice, not merged yet
        out.append(a)
        last = (n, a)
    return out


def _walk(container):
    '''Every assertion at or under `container`, depth first.'''
    for a in (*container.properties, *container.edges):
        yield a
        yield from _walk(a)


def resolve(g, policy: str | Callable = 'first') -> int:
    '''
    Settle claims that carry more than one `@ordering`, leaving each with exactly one. Returns how
    many claims were changed. It edits `g` in place, and only ever when you call it.

    `policy` is `'first'` (the lowest stamp), `'last'` (the highest), or a callable
    `(assertion, stamps) -> int` given the claim and its sorted distinct stamps. Claims with a stamp
    that isn't an integer are left alone: `ordered_values()` still reports them.
    '''
    if policy == 'first':
        pick = lambda a, nums: nums[0]  # noqa: E731
    elif policy == 'last':
        pick = lambda a, nums: nums[-1]  # noqa: E731
    elif callable(policy):
        pick = policy
    else:
        raise ValueError(f"policy must be 'first', 'last' or a callable, got {policy!r}")
    fixed = 0
    for n in list(g.nodes.values()):
        for a in list(_walk(n)):
            found = stamps(a)
            nums = {stamp_int(p.value) for p in found}
            if len(nums) < 2 or None in nums:
                continue
            chosen = pick(a, sorted(nums))
            for p in found:
                a.remove_property(p)
            a.add_property(ONYA_ORDERING, str(chosen))
            fixed += 1
    return fixed
