# -*- coding: utf-8 -*-
# test/test_inline_assertion_id.py
'''
Inline assertion ids (`* knows -> Ify [=chuks-ify-friendship]`) are parser-level sugar for a
nested `@id:` line: each document here, written both ways, parses to an identical graph (#18).

    pytest -s test/test_inline_assertion_id.py
'''

import pytest

from onya.serial import literate
from onya.serial.literate import LiterateSyntaxError
from onya.graph import AssertionIdConflict

from store.store_helpers import canon

HEADER = '''# @docheader
* @document: http://example.org/doc
* @nodebase: http://example.org/people/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab/

'''

# (inline form, nested-@id form) pairs covering each value form and nesting position
PAIRS = [
    ('''# Chuks [Person]
* knows -> Ify [=chuks-ify-friendship]
  * startDate: "2018-03-15"

# Ify [Person]
''', '''# Chuks [Person]
* knows -> Ify
  * @id: chuks-ify-friendship
  * startDate: "2018-03-15"

# Ify [Person]
'''),
    # unquoted, quoted, explicit-IRI, and CURIE-target values
    ('''# X
* name: Chuks Okafor [=x-name]
* alternateName: "Emeka: the elder" [=x-alt]
* sameAs -> <http://example.org/people/Ify> [=x-same]
* ex:role -> ex:Translator [=x-role]
''', '''# X
* name: Chuks Okafor
  * @id: x-name
* alternateName: "Emeka: the elder"
  * @id: x-alt
* sameAs -> <http://example.org/people/Ify>
  * @id: x-same
* ex:role -> ex:Translator
  * @id: x-role
'''),
    # the merge-hazard pattern: same value, different qualifier bundles, kept apart by ids
    ('''# nigeria [Country]
* ex:population: "5000000" [=pop-2023]
  * @as: number
  * temporalCoverage: "2023"
  * ex:source -> ex:CensusBureau
* ex:population: "5000000" [=pop-2024]
  * @as: number
  * temporalCoverage: "2024"
  * ex:source -> ex:UNData
''', '''# nigeria [Country]
* ex:population: "5000000"
  * @id: pop-2023
  * @as: number
  * temporalCoverage: "2023"
  * ex:source -> ex:CensusBureau
* ex:population: "5000000"
  * @as: number
  * @id: pop-2024
  * temporalCoverage: "2024"
  * ex:source -> ex:UNData
'''),
    # nested assertions can be named too, and an inline-named assertion can be an edge target
    ('''# Chuks [Person]
* knows -> Ify [=friendship]
  * startDate: "2018" [=friendship-start]

# ReviewNote
* disputes -> friendship-start
''', '''# Chuks [Person]
* knows -> Ify
  * @id: friendship
  * startDate: "2018"
    * @id: friendship-start

# ReviewNote
* disputes -> friendship-start
'''),
]


@pytest.mark.parametrize('inline,nested', PAIRS)
def test_inline_equals_nested(inline, nested):
    gi, gn = literate.read(HEADER + inline).graph, literate.read(HEADER + nested).graph
    assert canon(gi) == canon(gn)
    assert set(gi.assertion_ids) == set(gn.assertion_ids)


def test_merge_keeps_identified_bundles_apart():
    g = literate.read(HEADER + PAIRS[2][0], merge=True).graph
    pops = sorted(g['http://example.org/people/nigeria'].getprop('ex:population'),
                  key=lambda a: str(a.id))
    assert [str(p.id).rsplit('/', 1)[-1] for p in pops] == ['pop-2023', 'pop-2024']
    assert [p.any_prop_value('temporalCoverage') for p in pops] == ['2023', '2024']


def test_docheader_assertions_take_inline_ids():
    doc = '''# @docheader
* @document: http://example.org/doc
* @nodebase: http://example.org/people/
* @schema: https://schema.org/
* about -> Chuks [=doc-about]
'''
    g = literate.read(doc).graph
    assert str(g.assertion_ids['http://example.org/people/doc-about'].label) == 'https://schema.org/about'


@pytest.mark.parametrize('value', ['[=not-an-id]', '"literal [=kept]"'])
def test_literal_bracket_values_stay_text(value):
    g = literate.read(HEADER + f'# X\n* note: {value}\n').graph
    assert g.assertion_ids == {}
    assert g['http://example.org/people/X'].any_prop_value('note') == value.strip('"')


def test_inline_and_nested_id_on_one_assertion_is_an_error():
    with pytest.raises(LiterateSyntaxError, match='at most one id'):
        literate.read(HEADER + '# X\n* knows -> Ify [=a]\n  * @id: b\n')


def test_inline_id_collisions_are_still_caught():
    with pytest.raises(AssertionIdConflict):
        literate.read(HEADER + '# X\n* name: A [=dup]\n* alternateName: B [=dup]\n')
    with pytest.raises(AssertionIdConflict):          # an @id shares the node id space
        literate.read(HEADER + '# X\n* knows -> Y [=X]\n')


def test_write_emits_normative_nested_form():
    g = literate.read(HEADER + PAIRS[0][0]).graph
    import io
    out = io.StringIO()
    literate.write(g, out, nodebase='http://example.org/people/', schema='https://schema.org/')
    assert '* @id: chuks-ify-friendship' in out.getvalue() and '[=' not in out.getvalue()
    assert canon(literate.read(out.getvalue()).graph) == canon(g)
