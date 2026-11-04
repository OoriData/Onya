# -*- coding: utf-8 -*-
# test/test_reserved_vocab.py
'''
Reserved vocabulary (#62): every `@x` is `onya:x`; core reserves a fixed set, layers add theirs through
`onya.terms.reserve`, and `unknown_reserved_terms` reports what nothing reserves (a likely typo) without
ever making parsing fail.

    pytest -s test/test_reserved_vocab.py
'''

import re
from pathlib import Path

import pytest

from onya import terms
from onya.graph import graph
from onya.serial.literate import read
from onya.terms import ONYA, RESERVED, reserve, unknown_reserved_terms

SPEC = (Path(__file__).resolve().parent.parent / 'SPEC.md').read_text(encoding='utf-8')

DOC = '''# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

'''


@pytest.fixture
def registry():
    '''Run a test against a scratch copy of the registry, so a test's layer never leaks into another.'''
    saved = dict(RESERVED)
    yield RESERVED
    RESERVED.clear()
    RESERVED.update(saved)


def _spec_section() -> str:
    start = SPEC.index('## Reserved vocabulary')
    return SPEC[start:SPEC.index('\n## ', start + 1)]


def test_every_core_term_is_documented_in_the_spec():
    table = [ln for ln in _spec_section().splitlines() if ln.startswith('|')]  # the prose also mentions `@x`
    documented = set(re.findall(r'`@(\w+)`', ' '.join(ln.split('|')[1] for ln in table)))
    core = {name for name, layer in RESERVED.items() if layer == 'core'}
    assert core <= documented, f'core terms missing from SPEC: {sorted(core - documented)}'
    assert documented <= set(RESERVED), f'SPEC lists terms the registry lacks: {sorted(documented - set(RESERVED))}'


def test_every_core_term_has_a_constant_naming_it():
    constants = {name: value for name, value in vars(terms).items() if name.startswith('ONYA_')}
    named = {str(v)[len(str(ONYA)):] for v in constants.values() if str(v).startswith(str(ONYA))}
    core = {name for name, layer in RESERVED.items() if layer == 'core'}
    assert core <= named, f'core terms with no ONYA_* constant: {sorted(core - named)}'


def test_everything_the_parser_treats_as_a_directive_is_reserved():
    directives = ('document', 'nodebase', 'base', 'schema', 'typebase', 'language', 'iri', 'interpretations',
                  'id', 'as')
    for name in directives:
        assert RESERVED[name] == 'core'


def test_a_layer_adds_terms_without_touching_core(registry):
    reserve('ordering', 'ordering')
    assert registry['ordering'] == 'ordering'
    reserve('ordering', 'ordering')  # idempotent for the same layer


def test_a_layer_cannot_redefine_a_term(registry):
    with pytest.raises(ValueError, match='already reserved by'):
        reserve('shape', 'source')  # core's
    reserve('ordering', 'ordering')
    with pytest.raises(ValueError, match="'ordering'"):
        reserve('shape', 'ordering')  # another layer's


def test_typos_are_reported_and_still_parse():
    g = graph()
    read(DOC + '# A [@Calss]\n\n* @sourcee: x\n* name: A\n  * @confidence: 0.9\n', g)  # parses: not an error
    found = unknown_reserved_terms(g)
    assert {str(t) for t in found} == {str(ONYA('Calss')), str(ONYA('sourcee'))}
    assert found[ONYA('Calss')] == [g['http://e.o/A']]  # a type's use is its node
    (use,) = found[ONYA('sourcee')]
    assert str(use.label) == str(ONYA('sourcee'))  # a label's use is its assertion


def test_nested_assertion_labels_are_audited_too():
    g = graph()
    read(DOC + '# A\n\n* knows -> B\n  * @mehtod: x\n', g)
    assert [str(t) for t in unknown_reserved_terms(g)] == [str(ONYA('mehtod'))]


def test_known_terms_other_vocabularies_and_interps_are_not_reported():
    g = graph()
    read(DOC + '# A [Person]\n\n* name: A\n  * @source: x\n  * @as: number\n* age: 3\n  * @as: nope\n', g)
    g.node('http://e.o/D', types={ONYA('Document'), ONYA('interp/number'), 'https://other.example/Thing'})
    assert unknown_reserved_terms(g) == {}


def test_a_term_a_layer_reserves_stops_being_unknown(registry):
    g = graph()
    read(DOC + '# A\n\n* @ordering: x\n', g)
    assert [str(t) for t in unknown_reserved_terms(g)] == [str(ONYA('ordering'))]
    reserve('ordering', 'ordering')
    assert unknown_reserved_terms(g) == {}


def test_a_full_iri_in_the_vocabulary_is_the_same_term_as_the_at_form():
    g = graph()
    read(DOC + '# A\n\n* <http://purl.org/onya/vocab/Calss>: x\n', g)
    assert [str(t) for t in unknown_reserved_terms(g)] == [str(ONYA('Calss'))]
