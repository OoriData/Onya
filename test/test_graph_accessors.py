# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# test/test_graph_accessors.py
'''
Projection accessors (#55): `values`, `targets`, `one`, `one_target`, and `CardinalityError`.

    pytest -s test/test_graph_accessors.py
'''

import pytest
from amara.iri import I

from onya.graph import CardinalityError
from onya.serial.literate import read

DOC = '''# @docheader
* @document: http://example.org/doc
* @nodebase: http://example.org/kg/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab

# acme [Organization]
* name: Acme LLC
* telephone: "+1 555 0100"
* telephone: "+1 555 0101"
* ex:tag: b
* ex:tag: a
* parentOrganization -> holdco
* member -> zed
  * ex:since: "2020"
  * ex:since: "2021"
* member -> amy

# holdco [Organization]
# zed [Person]
# amy [Person]
'''
SCHEMA = I('https://schema.org/')


@pytest.fixture
def acme():
    g = read(DOC).graph
    acme = g['http://example.org/kg/acme']
    acme.g = g  # nodes hold their graph weakly: keep it alive so prefixes resolve
    return acme


LABEL_FORMS = ('{0}', 'https://schema.org/{0}', 'schema:{0}', '{0}')  # I, full IRI, CURIE, bare name


def forms(name):
    return [SCHEMA(name)] + [f.format(name) for f in LABEL_FORMS[1:]]


@pytest.mark.parametrize('label', forms('telephone'))
def test_label_forms_agree(acme, label):
    assert acme.values(label) == ['+1 555 0100', '+1 555 0101']


@pytest.mark.parametrize('label', forms('member'))
def test_target_label_forms_agree(acme, label):
    assert [str(t.id) for t in acme.targets(label)] == ['http://example.org/kg/amy', 'http://example.org/kg/zed']


def test_values_are_a_deterministic_list(acme):
    assert acme.values('ex:tag') == ['a', 'b']  # sorted, whatever the set's iteration order
    assert acme.values('ex:nothing') == [] and acme.targets('ex:nothing') == []


def test_one(acme):
    assert acme.one('name') == 'Acme LLC'
    assert acme.one('ex:nothing') is None
    assert acme.one('ex:nothing', default='n/a') == 'n/a'


def test_one_raises_with_what_it_found(acme):
    with pytest.raises(CardinalityError) as ei:
        acme.one('telephone')
    e = ei.value
    assert e.origin is acme and e.label == SCHEMA('telephone') and e.found == ['+1 555 0100', '+1 555 0101']
    assert 'telephone' in str(e) and 'acme' in str(e)


def test_one_target(acme):
    assert str(acme.one_target('parentOrganization').id) == 'http://example.org/kg/holdco'
    assert acme.one_target('ex:nothing') is None
    with pytest.raises(CardinalityError) as ei:
        acme.one_target('member')
    assert ei.value.found == ['http://example.org/kg/amy', 'http://example.org/kg/zed']


def test_identical_occurrences_are_one_claim():
    g = read(DOC.replace('* name: Acme LLC\n', '* name: Acme LLC\n* name: Acme LLC\n')).graph
    acme = g['http://example.org/kg/acme']
    assert acme.one('name') == 'Acme LLC'  # two occurrences, one distinct value: not a conflict


def test_accessors_work_on_nested_assertions(acme):
    zed = next(e for e in acme.getedge('member') if e.target.id.endswith('zed'))
    assert zed.values('ex:since') == ['2020', '2021']
    with pytest.raises(CardinalityError):
        zed.one('ex:since')
