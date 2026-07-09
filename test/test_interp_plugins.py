# -*- coding: utf-8 -*-
# test_interp_plugins.py
'''
Tests for the interpretation plugin layer (onya.interp): the Onya Lightweight Types, the
registry, and the application API. Contracts are honored on demand, never ambiently — the
model stores strings and the parser never invokes this layer.

    pytest -s test/test_interp_plugins.py
'''

import datetime
from decimal import Decimal

import pytest

from amara.iri import I

from onya.graph import graph
from onya.terms import ONYA_INTERP
from onya.serial.literate import LiterateParser
from onya.interp import (
    DEFAULT,
    InterpretationRegistry,
    InterpretationError,
    UnknownInterpretation,
    value_of,
    set_value,
    validate,
    unknown_interps,
)


NUMBER = ONYA_INTERP('number')
DATETIME = ONYA_INTERP('datetime')
BOOLEAN = ONYA_INTERP('boolean')
IRI = ONYA_INTERP('iri')
TEXT = ONYA_INTERP('text')


def _prop(value, interp_iri=None):
    '''A standalone property assertion carrying `value` and optional interp.'''
    g = graph()
    n = g.node(I('http://e.o/N'))
    return n.add_property(I('https://schema.org/p'), value, interp=interp_iri)


# --- number -------------------------------------------------------------------------

def test_number_integer_literal_is_int():
    num = DEFAULT.get(NUMBER)
    assert num.to_python('28') == 28
    assert isinstance(num.to_python('28'), int)


def test_number_fraction_is_decimal_not_float():
    num = DEFAULT.get(NUMBER)
    lon = num.to_python('-105.2705')
    assert lon == Decimal('-105.2705')
    assert isinstance(lon, Decimal)  # never a binary float


def test_number_exponent_is_decimal():
    num = DEFAULT.get(NUMBER)
    assert num.to_python('6.02214076e23') == Decimal('6.02214076E+23')


@pytest.mark.parametrize('s', ['28', '-0', '0', '+7', '-105.2705', '6.02214076e23',
                               '0.00000000001', '1.50', '.5', '1e-9', '-3.14159265358979'])
def test_number_roundtrip_law(s):
    '''to_python(from_python(to_python(s))) == to_python(s) — equivalence through the value.'''
    num = DEFAULT.get(NUMBER)
    assert num.check(s)
    once = num.to_python(s)
    twice = num.to_python(num.from_python(once))
    assert twice == once


def test_number_from_python_shortest_exact():
    num = DEFAULT.get(NUMBER)
    assert num.from_python(num.to_python('-105.2705')) == '-105.2705'
    assert num.from_python(28) == '28'


def test_number_rejects_non_numbers():
    num = DEFAULT.get(NUMBER)
    assert not num.check('spring')
    assert not num.check('')
    with pytest.raises(InterpretationError):
        num.to_python('spring')


def test_number_from_python_refuses_bool():
    '''bool is an int subclass but is not a number here.'''
    num = DEFAULT.get(NUMBER)
    with pytest.raises(TypeError):
        num.from_python(True)


# --- datetime -----------------------------------------------------------------------

def test_datetime_date_and_datetime():
    dt = DEFAULT.get(DATETIME)
    assert dt.to_python('2018-03-15') == datetime.date(2018, 3, 15)
    assert dt.to_python('2018-03-15T10:30:00') == datetime.datetime(2018, 3, 15, 10, 30, 0)


def test_datetime_roundtrip_law():
    dt = DEFAULT.get(DATETIME)
    for s in ('2018-03-15', '2018-03-15T10:30:00'):
        once = dt.to_python(s)
        assert dt.to_python(dt.from_python(once)) == once


def test_datetime_spring_1958_is_finding_not_rejection():
    '''The foundation accepts "spring 1958"; the boundary reports it.'''
    dt = DEFAULT.get(DATETIME)
    assert not dt.check('spring 1958')
    with pytest.raises(InterpretationError):
        dt.to_python('spring 1958')


# --- boolean ------------------------------------------------------------------------

def test_boolean_exact_only():
    b = DEFAULT.get(BOOLEAN)
    assert b.check('true') and b.check('false')
    assert not b.check('True')  # LLM-typical, does NOT check
    assert not b.check('yes')
    assert b.to_python('true') is True
    assert b.to_python('false') is False
    assert b.from_python(True) == 'true'


# --- iri ----------------------------------------------------------------------------

def test_iri_check_and_convert():
    it = DEFAULT.get(IRI)
    assert it.check('http://example.org/x')
    assert it.to_python('http://example.org/x') == I('http://example.org/x')
    assert it.from_python(I('http://example.org/x')) == 'http://example.org/x'


# --- text ---------------------------------------------------------------------------

def test_text_accepts_anything_unchanged():
    t = DEFAULT.get(TEXT)
    assert t.check('0042')
    assert t.to_python('0042') == '0042'  # leading zero preserved, not "fixed" to 42
    assert t.from_python('0042') == '0042'


# --- registry -----------------------------------------------------------------------

def test_registry_collision_raises():
    reg = InterpretationRegistry()
    reg.register(_Lax())
    with pytest.raises(ValueError, match='already registered'):
        reg.register(_Lax())


def test_registry_replace_allows_override():
    reg = InterpretationRegistry()
    reg.register(_Lax())
    reg.register(_Lax(), replace=True)  # no raise
    assert I('http://e.o/interp/lax') in reg


def test_registry_str_and_iri_lookups_agree():
    assert DEFAULT.get('http://purl.org/onya/vocab/interp/number') is DEFAULT.get(NUMBER)
    assert NUMBER in DEFAULT


class _Lax:
    '''A tiny custom interpretation for registry tests (leniency is its own contract).'''
    iri = I('http://e.o/interp/lax')

    def check(self, v):
        return v.strip().lower() in {'true', 'false', 'yes', 'no', '1', '0'}

    def to_python(self, v):
        return v.strip().lower() in {'true', 'yes', '1'}

    def from_python(self, b):
        return 'true' if b else 'false'


# --- value_of / set_value -----------------------------------------------------------

def test_value_of_no_interp_passthrough():
    p = _prop('28')  # no interp
    assert value_of(p) == '28'


def test_value_of_converts_with_interp():
    p = _prop('28', NUMBER)
    assert value_of(p) == 28


def test_value_of_strict_unknown_raises():
    unknown = I('http://fintech.example/interp/RiskScore')
    p = _prop('0.87', unknown)
    with pytest.raises(UnknownInterpretation):
        value_of(p)


def test_value_of_non_strict_unknown_returns_raw():
    unknown = I('http://fintech.example/interp/RiskScore')
    p = _prop('0.87', unknown)
    assert value_of(p, strict=False) == '0.87'


def test_value_of_conversion_failure_carries_assertion():
    p = _prop('spring 1958', DATETIME)
    with pytest.raises(InterpretationError) as excinfo:
        value_of(p)
    assert excinfo.value.assertion is p


def test_set_value_is_inverse_of_value_of():
    g = graph()
    n = g.node(I('http://e.o/N'))
    p = set_value(n, I('https://schema.org/height'), Decimal('1.85'), NUMBER)
    assert p.value == '1.85'
    assert p.interp == NUMBER
    assert value_of(p) == Decimal('1.85')


def test_set_value_unknown_interp_raises():
    g = graph()
    n = g.node(I('http://e.o/N'))
    with pytest.raises(UnknownInterpretation):
        set_value(n, I('https://schema.org/x'), 1, I('http://e.o/interp/nope'))


# --- validate / unknown_interps -----------------------------------------------------

def _graph_with(*triples):
    '''Build a one-node graph; each triple is (label_local, value, interp_iri_or_None).'''
    g = graph()
    n = g.node(I('http://e.o/Chuks'))
    for label, value, interp_iri in triples:
        n.add_property(I('https://e.o/v/' + label), value, interp=interp_iri)
    return g


def test_validate_findings_only_for_known_and_failing():
    g = _graph_with(
        ('verified', 'true', BOOLEAN),          # valid -> no finding
        ('active', 'True', BOOLEAN),            # known + failing -> finding
        ('member', 'yes', BOOLEAN),             # known + failing -> finding
        ('risk', '0.87', I('http://x/Unknown')),  # unknown -> no finding
        ('name', 'Chuks', None),                # absent interp -> no finding
    )
    report = validate(g)
    assert not report.ok
    failed = {str(f.assertion.label) for f in report.findings}
    assert failed == {'https://e.o/v/active', 'https://e.o/v/member'}


def test_validate_is_data_never_raises():
    '''A wildly invalid value is a finding, not an exception. Graph stays valid Onya.'''
    g = _graph_with(('birthDate', 'spring 1958', DATETIME))
    report = validate(g)  # does not raise
    assert len(report.findings) == 1
    assert 'ISO 8601' in str(report)


def test_validate_all_valid_is_ok():
    g = _graph_with(('age', '28', NUMBER), ('verified', 'true', BOOLEAN))
    assert validate(g).ok


def test_unknown_interps_maps_iris_to_assertions():
    unknown = I('http://fintech.example/interp/RiskScore')
    g = _graph_with(('risk', '0.87', unknown), ('age', '28', NUMBER))
    um = unknown_interps(g)
    assert set(um) == {unknown}
    assert len(um[unknown]) == 1
    assert um[unknown][0].value == '0.87'


# --- never ambient ------------------------------------------------------------------

DOC = '''\
# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* active: True
  * @as: boolean
'''


def test_parsing_never_applies_interpretations():
    '''Parsing records the contract and leaves the string untouched — no ambient checking.

    The parser takes no registry and imports nothing from onya.interp, so the graph is
    identical whether or not interpretations are installed. A value that would fail a
    boolean check ('True') parses fine and is stored verbatim; checking happens only at
    validate(), a boundary the caller chooses.
    '''
    g_default = graph()
    LiterateParser().parse(DOC, g_default)
    active = next(g_default['http://e.o/Chuks'].getprop('https://schema.org/active'))
    assert active.value == 'True'          # unchanged, never coerced
    assert active.interp == BOOLEAN        # the contract, recorded as data

    # Honoring it against an EMPTY registry vs DEFAULT differs only at the boundary,
    # never in the graph itself.
    empty = InterpretationRegistry()
    assert value_of(active, registry=empty, strict=False) == 'True'
    assert validate(g_default, registry=empty).ok  # empty knows nothing -> no findings
    assert not validate(g_default, registry=DEFAULT).ok  # DEFAULT checks -> a finding


# --- property-based round-trip law (hypothesis, test-only) --------------------------

hypothesis = pytest.importorskip('hypothesis')
from hypothesis import given, strategies as st  # noqa: E402


@given(st.integers())
def test_number_roundtrip_law_integers(n):
    num = DEFAULT.get(NUMBER)
    s = str(n)
    assert num.check(s)
    once = num.to_python(s)
    assert num.to_python(num.from_python(once)) == once


@given(st.decimals(allow_nan=False, allow_infinity=False))
def test_number_roundtrip_law_decimals(d):
    num = DEFAULT.get(NUMBER)
    s = str(d)
    if not num.check(s):  # str(Decimal) can produce forms our grammar excludes; skip those
        return
    once = num.to_python(s)
    assert num.to_python(num.from_python(once)) == once
