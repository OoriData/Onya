# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.interp
'''
Interpretation (data-contract) plugin layer for Onya.

An *interpretation* is a recorded promise about how a string value is meant to be read —
a number, a datetime, a boolean, an IRI, prose. The Onya graph always stores the string,
and the string layer is unconditionally valid; this module honors contracts *at
boundaries, on demand*, and never ambiently. Parsing a graph never invokes anything here,
and a graph parses, merges, and round-trips identically regardless of which plugins are
installed (see doc/design-interpretations-pylib.md).

Nothing in the core model or the parser imports this module. The parser records
interpretation IRIs (via `@as` / `@interpretations`); converting or validating with them
is entirely the application's choice, expressed through the functions below.
'''

from __future__ import annotations

import re
import datetime as _datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Protocol, runtime_checkable

from amara import iri as _iri
from amara.iri import I

from onya.terms import ONYA_INTERP


__all__ = [
    'Interpretation',
    'InterpretationError',
    'UnknownInterpretation',
    'InterpretationRegistry',
    'DEFAULT',
    'Finding',
    'ValidationReport',
    'value_of',
    'set_value',
    'validate',
    'unknown_interps',
]


# --- errors -------------------------------------------------------------------------

class InterpretationError(ValueError):
    '''
    Raised by `to_python` when a string does not satisfy its interpretation (a broken
    promise demanded at a boundary). Carries the offending `value`, the `interp_iri`, and —
    when a boundary call can supply it — the `assertion`, so a caller can point at the
    graph. `check()` returning False is the non-raising counterpart; this is raised only
    when a consumer actually demands the converted value.
    '''
    def __init__(self, value, interp_iri, assertion=None, message=None):
        self.value = value
        self.interp_iri = interp_iri
        self.assertion = assertion
        super().__init__(message or f'{value!r} is not a valid {interp_iri}')


class UnknownInterpretation(ValueError):
    '''
    Raised by `value_of(..., strict=True)` when the data carries an interpretation the
    registry has never heard of. The data is fine — the contract simply cannot be honored
    here. `strict=False` waives the contract and returns the raw string instead.
    '''
    def __init__(self, interp_iri, assertion=None):
        self.interp_iri = interp_iri
        self.assertion = assertion
        super().__init__(f'No interpretation registered for {interp_iri}')


# --- the plugin contract ------------------------------------------------------------

@runtime_checkable
class Interpretation(Protocol):
    '''
    A data contract about how a string value is read. Round-trip law: for any string `s`
    with `check(s)` true, `to_python(from_python(to_python(s)))` equals `to_python(s)` —
    equivalence *through the Python value*, not byte identity of strings.
    '''
    iri: I

    def check(self, value: str) -> bool:
        '''Is `value` a well-formed instance? Never raises.'''

    def to_python(self, value: str) -> object:
        '''Convert to a useful Python object, or raise `InterpretationError`.'''

    def from_python(self, obj: object) -> str:
        '''Render a Python object back to canonical string form.'''


# --- Onya Lightweight Types (the starter set) ---------------------------------------

# number: optional sign; decimal integer or fraction; optional exponent.
_NUMBER_RE = re.compile(r'^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$')


def _canonical_number(d: Decimal) -> str:
    '''
    Shortest exact decimal form for a `Decimal`. Trailing zeros are stripped via
    `normalize()`, but under a local context wide enough to hold every digit — the default
    28-digit context would *round* a high-precision value and break the round-trip law.
    Plain (fixed-point) notation is preferred for human-scale magnitudes, with the
    exponent form kept only for very large/small numbers; either form is exact.
    '''
    with localcontext() as ctx:
        ctx.prec = max(len(d.as_tuple().digits), 1)
        d = d.normalize()
    _sign, _digits, exp = d.as_tuple()
    if isinstance(exp, int) and -25 < exp <= 6:
        return f'{d:f}'
    return str(d)


class _Number:
    '''
    number — `to_python` yields `int` for an integer literal (no point, no exponent),
    else `decimal.Decimal`. Never a binary `float`: that would violate the round-trip law
    (e.g. `-105.2705` is not exactly representable in binary). Canonical `from_python`
    form is the shortest exact decimal.
    '''
    iri = ONYA_INTERP('number')

    def check(self, value: str) -> bool:
        return bool(_NUMBER_RE.match(value))

    def to_python(self, value: str):
        if not self.check(value):
            raise InterpretationError(value, self.iri, message=f'{value!r} is not a number')
        if '.' not in value and 'e' not in value and 'E' not in value:
            return int(value)
        try:
            return Decimal(value)
        except InvalidOperation:  # pragma: no cover - guarded by check()
            raise InterpretationError(value, self.iri, message=f'{value!r} is not a number')

    def from_python(self, obj) -> str:
        if isinstance(obj, bool):  # bool is an int subclass; refuse it as a number
            raise TypeError(f'{obj!r} is a bool, not a number')
        if isinstance(obj, int):
            return str(obj)
        if isinstance(obj, Decimal):
            return _canonical_number(obj)
        # A float would smuggle binary drift back in; route through str() for exactness.
        return _canonical_number(Decimal(str(obj)))


class _Datetime:
    '''
    datetime — ISO 8601 date (`2018-03-15`) or datetime, optional zone. `to_python` yields
    `datetime.date` or `datetime.datetime`; canonical `from_python` is ISO 8601.
    '''
    iri = ONYA_INTERP('datetime')

    def _parse(self, value: str):
        # A time component (`T` or a clock `:`) means datetime; otherwise a plain date.
        if 'T' in value or ':' in value:
            return _datetime.datetime.fromisoformat(value)
        return _datetime.date.fromisoformat(value)

    def check(self, value: str) -> bool:
        try:
            self._parse(value)
            return True
        except ValueError:
            return False

    def to_python(self, value: str):
        try:
            return self._parse(value)
        except ValueError:
            raise InterpretationError(value, self.iri, message=f'{value!r} is not ISO 8601 date/datetime')

    def from_python(self, obj) -> str:
        if isinstance(obj, (_datetime.date, _datetime.datetime)):
            return obj.isoformat()
        raise TypeError(f'{obj!r} is not a date or datetime')


class _Boolean:
    '''
    boolean — exactly `true` or `false`, case-sensitive. Leniency (`True`, `yes`, `1`) is a
    *different* contract a caller registers deliberately, not fine print on this one.
    '''
    iri = ONYA_INTERP('boolean')

    def check(self, value: str) -> bool:
        return value in ('true', 'false')

    def to_python(self, value: str) -> bool:
        if value == 'true':
            return True
        if value == 'false':
            return False
        raise InterpretationError(
            value, self.iri, message=f"{value!r} is not boolean (expected 'true'|'false')"
        )

    def from_python(self, obj) -> str:
        return 'true' if obj else 'false'


class _Iri:
    '''
    iri — IRI-reference syntax (via `amara.iri`), with no base resolution: `check` accepts
    relative references, and resolving them is the caller's concern. `to_python` yields
    `amara.iri.I`; canonical `from_python` is the IRI string.
    '''
    iri = ONYA_INTERP('iri')

    def check(self, value: str) -> bool:
        try:
            return bool(_iri.matches_uri_ref_syntax(value))
        except Exception:  # never raise from check
            return False

    def to_python(self, value: str) -> I:
        if not self.check(value):
            raise InterpretationError(value, self.iri, message=f'{value!r} is not an IRI reference')
        return I(value)

    def from_python(self, obj) -> str:
        return str(obj)


class _Text:
    '''
    text — anything. A positive assertion that the value is prose (so `0042` will not get
    "fixed" to 42 downstream). Distinct from `none`, which is not an interpretation at all.
    '''
    iri = ONYA_INTERP('text')

    def check(self, value: str) -> bool:
        return True

    def to_python(self, value: str) -> str:
        return value

    def from_python(self, obj) -> str:
        return str(obj)


# --- registry -----------------------------------------------------------------------

class InterpretationRegistry:
    '''
    A name -> interpretation map. Registering under an IRI already present raises unless
    `replace=True` — silently shadowing an interpretation is how two libraries quietly
    disagree about data. Keys are normalized to `amara.iri.I`, so `str` and `I` lookups
    agree.
    '''
    def __init__(self):
        self._by_iri: dict[I, Interpretation] = {}

    def register(self, interp: Interpretation, *, replace: bool = False) -> Interpretation:
        key = I(str(interp.iri))
        if not replace and key in self._by_iri:
            raise ValueError(f'Interpretation {key} already registered (pass replace=True to override)')
        self._by_iri[key] = interp
        return interp

    def get(self, iri) -> Interpretation | None:
        return self._by_iri.get(I(str(iri)))

    def __contains__(self, iri) -> bool:
        return I(str(iri)) in self._by_iri


def _default_registry() -> InterpretationRegistry:
    reg = InterpretationRegistry()
    for interp in (_Number(), _Datetime(), _Boolean(), _Iri(), _Text()):
        reg.register(interp)
    return reg


# Module-level registry preloaded with the Onya Lightweight Types. Applications may build
# private registries; every API below takes `registry=DEFAULT`. Treat DEFAULT as
# append-only in library code — no entry-point autodiscovery in phase 1.
DEFAULT = _default_registry()


# --- validation report --------------------------------------------------------------

@dataclass
class Finding:
    '''A single broken promise: a known interpretation whose `check` failed on a value.'''
    assertion: object
    interp_iri: I
    value: str
    message: str


@dataclass
class ValidationReport:
    '''
    The result of auditing a graph's contracts. Findings are data, never exceptions: a
    failed `check` is reported here; the graph itself is untouched and fully valid Onya.
    '''
    findings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def __str__(self) -> str:
        if not self.findings:
            return 'ValidationReport: ok (no findings)'
        return '\n'.join(
            f'{f.assertion.label} on {_origin_id(f.assertion)}: {f.message}'
            for f in self.findings
        )


def _origin_id(assertion):
    origin = getattr(assertion, 'origin', None)
    return getattr(origin, 'id', origin)


# --- graph traversal helpers --------------------------------------------------------

def _iter_assertions(container):
    '''Yield every assertion under `container`, recursively (properties and edges).'''
    for prop in container.properties:
        yield prop
        yield from _iter_assertions(prop)
    for edge in container.edges:
        yield edge
        yield from _iter_assertions(edge)


def _all_assertions(graph):
    for n in graph.nodes.values():
        yield from _iter_assertions(n)


# --- application API (on demand, never ambient) -------------------------------------

def value_of(prop, *, registry: InterpretationRegistry = DEFAULT, strict: bool = True):
    '''
    The property's value, converted via its interpretation. No interp -> the string
    unchanged. Interp unknown to the registry -> `UnknownInterpretation` when strict (the
    default), else the raw string (the caller explicitly waiving the contract). A malformed
    value raises `InterpretationError` carrying the assertion.
    '''
    interp_iri = getattr(prop, 'interp', None)
    if interp_iri is None:
        return prop.value
    interp = registry.get(interp_iri)
    if interp is None:
        if strict:
            raise UnknownInterpretation(interp_iri, prop)
        return prop.value
    try:
        return interp.to_python(prop.value)
    except InterpretationError as e:
        if e.assertion is None:
            e.assertion = prop
        raise


def set_value(origin, label, py_obj, interp_iri, *, registry: InterpretationRegistry = DEFAULT):
    '''
    Builder inverse of `value_of`: render `py_obj` via the interpretation's `from_python`
    and add a property carrying both the string and the interp. The interpretation must be
    registered (rendering needs it); the resulting assertion records `interp_iri` as data.
    '''
    interp = registry.get(interp_iri)
    if interp is None:
        raise UnknownInterpretation(interp_iri)
    return origin.add_property(label, interp.from_python(py_obj), interp=interp_iri)


def validate(graph, *, registry: InterpretationRegistry = DEFAULT) -> ValidationReport:
    '''
    Audit the graph's contracts: for each assertion whose interp the registry knows, run
    `check()`. A failed check is a finding — a broken promise reported as data — never an
    exception. Valid, unknown, and absent interps produce no finding (`unknown_interps`
    surfaces the unknown ones).
    '''
    findings: list[Finding] = []
    for assertion in _all_assertions(graph):
        interp_iri = getattr(assertion, 'interp', None)
        if interp_iri is None:
            continue
        interp = registry.get(interp_iri)
        if interp is None:  # unknown -> not a finding; see unknown_interps
            continue
        value = getattr(assertion, 'value', None)
        if value is None:  # edges carry no value (and never an interp); nothing to check
            continue
        if interp.check(value):
            continue
        # Reuse to_python's specific message where it has one.
        try:
            interp.to_python(value)
            message = f'{value!r} is not a valid {interp_iri}'
        except InterpretationError as e:
            message = str(e)
        findings.append(Finding(assertion, I(str(interp_iri)), value, message))
    return ValidationReport(findings)


def unknown_interps(graph, *, registry: InterpretationRegistry = DEFAULT) -> dict:
    '''
    Interpretation IRIs present in the graph but absent from the registry, mapped to the
    assertions carrying them — the "what would I need to plug in to honor everything here?"
    question. Answers nothing about validity; it is purely about coverage.
    '''
    result: dict[I, list] = {}
    for assertion in _all_assertions(graph):
        interp_iri = getattr(assertion, 'interp', None)
        if interp_iri is None:
            continue
        if interp_iri in registry:
            continue
        result.setdefault(I(str(interp_iri)), []).append(assertion)
    return result
