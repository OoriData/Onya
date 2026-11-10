# -*- coding: utf-8 -*-
# test/store/test_store_validate.py
'''
``validate_against_store``: ``validate(fragment, against=base)`` for a base held in a store, on every backend.

    pytest -s test/store/test_store_validate.py
'''

import pytest

from onya.shape import validate_against_store
from store_helpers import DOCHEADER as _SCHEMA_ORG_HEAD, parse

DOCHEADER = _SCHEMA_ORG_HEAD.replace('https://schema.org/', 'http://e.o/')  # labels and types where the shapes are

SHAPES = '''
# Person [@Class]
# Student [@Class]
* @subClassOf -> Person
# Org [@Class]

# name [@Property]
* @appliesTo -> Person
* @cardinality: 1
# knows [@Property]
* @appliesTo -> Person
* @range -> Person
'''
BASE = DOCHEADER.replace('http://e.o/doc', 'http://e.o/base') + SHAPES + '''
# chuks [Student]
* name: Chuks
# acme [Org]
# nameless [Person]
'''
BASE_NAME = 'http://e.o/base'
RUNTIME_NAME = 'http://e.o/runtime'
RUNTIME = DOCHEADER.replace('http://e.o/doc', RUNTIME_NAME) + '\n# ada [Person]\n* name: Ada\n'


def frag(body: str):
    return parse(DOCHEADER + '\n' + body)


async def test_a_stored_base_resolves_types_and_cardinality(store):
    await store.put(BASE_NAME, parse(BASE))
    ok = await validate_against_store(frag('# ify [Person]\n* name: Ify\n* knows -> chuks\n'), store, BASE_NAME)
    assert ok.findings == []  # chuks is a Student in the store: a Person; the shapes came from the store too
    wrong = await validate_against_store(frag('# ify [Person]\n* name: Ify\n* knows -> acme\n'), store, BASE_NAME)
    assert [(f.kind, str(f.node)) for f in wrong.findings] == [('range', 'http://e.o/ify')]
    second = await validate_against_store(frag('# chuks [Student]\n* name: Other\n'), store, BASE_NAME)
    assert [(f.kind, f.detail) for f in second.findings] == [('cardinality', 'has 2, declared 1')]


async def test_the_stored_bases_own_problems_are_not_reported(store):
    await store.put(BASE_NAME, parse(BASE))  # `nameless` has no name
    r = await validate_against_store(frag('# ify [Person]\n* name: Ify\n'), store, BASE_NAME)
    assert r.findings == []


async def test_several_graphs_are_the_base_together_and_a_missing_one_is_skipped(store):
    await store.put(BASE_NAME, parse(BASE))
    names = [BASE_NAME, RUNTIME_NAME]  # the runtime graph does not exist yet
    f = frag('# ify [Person]\n* name: Ify\n* knows -> ada\n')
    assert [x.kind for x in (await validate_against_store(f, store, names)).findings] == ['range']  # `ada` is unknown
    await store.put(RUNTIME_NAME, parse(RUNTIME))
    assert (await validate_against_store(f, store, names)).findings == []  # now she is stored, in the other graph


async def test_nothing_stored_means_the_fragment_stands_alone(store):
    r = await validate_against_store(frag('# ify [Person]\n* name: Ify\n'), store, BASE_NAME, shapes=parse(SHAPES))
    assert r.findings == []


async def test_a_store_with_subgraph_never_reads_the_whole_graph(store, backend, monkeypatch):
    if backend == 'file':
        pytest.skip('the file store has no subgraph: it reads the graph')
    await store.put(BASE_NAME, parse(BASE))

    async def no_get(name):
        raise AssertionError('the whole graph was read')

    monkeypatch.setattr(store, 'get', no_get)
    r = await validate_against_store(frag('# ify [Person]\n* name: Ify\n* knows -> chuks\n'), store, BASE_NAME)
    assert r.findings == []
