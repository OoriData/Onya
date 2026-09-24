# -*- coding: utf-8 -*-
# test/store/test_store_view.py
'''
``view.project_from_store`` equals ``view.project`` over the whole graph on every backend,
without ``get()`` on SQL stores; plus ``AssertionStore.match(target=)``.

    pytest -s test/store/test_store_view.py
'''

import pytest
from amara.iri import I

from onya import view
from onya.serial import literate
from onya.store import AssertionStore

NAME = I('http://example.org/graphs/lib')
L = 'http://example.org/lib/'
SCHEMA = 'https://schema.org/'

DOC = '''# @docheader
* @nodebase: http://example.org/lib/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab/

# ada [Person]
* name: Ada Lovelace
* email: ada@example.org
* worksFor -> aec
    * startDate: "1842"
    * ex:role -> ex:Translator
* knows -> babbage

# babbage [Person]
* name: Charles Babbage
* knows -> ada
* knows -> menabrea

# menabrea [Person]
* name: Luigi Menabrea

# notes [Book]
* name: Notes on the Analytical Engine
* datePublished: "1843"
* author -> ada

# aec [Organization]
* name: Analytical Engine Company

# http://example.org/vocab/Translator [DefinedTerm]
* name: Translator
'''

SPECS = [
    {'type': 'Person', 'fields': ['name', {'label': 'email', 'many': True}], 'follow': [
        {'edge': 'worksFor', 'as': 'employer', 'show': ['name'],
         'edge_props': ['startDate', {'edge': 'ex:role', 'as': 'role', 'show': ['name']}]},
        {'inbound': 'author', 'as': 'works', 'show': ['name', 'datePublished']},
        {'edge': 'knows'},                           # show-less: the target's own view, recursively
    ]},
    {'type': 'Organization', 'fields': ['name'],
     'follow': [{'inbound': 'worksFor', 'as': 'staff', 'show': ['name']}]},
]


@pytest.mark.parametrize('root', ['ada', 'babbage', 'aec', 'notes'])
@pytest.mark.parametrize('max_depth', [1, 3])
async def test_project_from_store_equals_in_memory(store, backend, root, max_depth):
    r = literate.read(DOC)
    await store.put(NAME, r.graph)
    expected = view.project(literate.read(DOC).graph, L + root, SPECS, max_depth=max_depth)
    if isinstance(store, AssertionStore):
        async def no_get(*a, **k):
            raise AssertionError('project_from_store must not load the whole graph')
        store.get = no_get
    got = await view.project_from_store(store, NAME, L + root, SPECS, prefixes=r.graph.prefixes,
                                        max_depth=max_depth)
    assert got == expected


async def test_project_from_store_absent_node(store):
    await store.put(NAME, literate.read(DOC).graph)
    with pytest.raises(KeyError):
        await view.project_from_store(store, NAME, L + 'nobody', SPECS, prefixes=literate.read(DOC).graph.prefixes)


async def test_match_target(store):
    if not isinstance(store, AssertionStore):
        pytest.skip('filesystem backend is not an AssertionStore')
    await store.put(NAME, literate.read(DOC).graph)
    rows = [r async for r in store.match(NAME, label=I(SCHEMA + 'knows'), target=L + 'ada')]
    assert [(str(o), str(t)) for o, _, t, _ in rows] == [(L + 'babbage', L + 'ada')]
    rows = [r async for r in store.match(NAME, target=L + 'aec')]
    assert [str(o) for o, *_ in rows] == [L + 'ada']
