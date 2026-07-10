# -*- coding: utf-8 -*-
# test/store/test_store_conformance.py
'''
Behavioral conformance suite, written once and run against every backend via the ``store``
fixture. A backend is correct exactly when a round trip through it is indistinguishable from
an in-memory graph union — so every merge case is asserted equal to ``reference(...)``, the
model union of the same inputs.

    pytest -s test/store/test_store_conformance.py
    ONYA_TEST_PG_DSN=postgresql://... pytest -s test/store/   # also exercise PostgreSQL
'''

import pytest

from onya.graph import AssertionIdConflict, GraphMergeError, graph
from onya.serial.literate import LiterateParser

from store_helpers import DOCHEADER, NAME, canon, parse, reference


AGE = 'https://schema.org/age'
KNOWS = 'https://schema.org/knows'
CHUKS = 'http://e.o/Chuks'


# --- round-trip of the fixture documents --------------------------------------------

@pytest.mark.parametrize('fixture', ['thingsfallapart.onya', 'achebe-bio.onya'])
async def test_fixture_roundtrip(store, here_testresource, fixture):
    text = (here_testresource / 'schemaorg' / fixture).read_text()
    r = LiterateParser().parse(text)
    await store.put(r.doc_iri, r.graph, merge=False)
    got = await store.get(r.doc_iri)
    assert canon(got) == canon(r.graph)


# --- basic put/get semantics --------------------------------------------------------

async def test_put_merge_false_replaces(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Ada [Person]\n\n* age: 31\n'
    await store.put(NAME, parse(a), merge=False)
    await store.put(NAME, parse(b), merge=False)
    got = await store.get(NAME)
    assert canon(got) == canon(parse(b))          # b wholly replaced a
    assert CHUKS not in got.nodes


async def test_put_merge_true_idempotent(store):
    doc = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n* knows -> Ify\n'
    await store.put(NAME, parse(doc), merge=True)
    await store.put(NAME, parse(doc), merge=True)   # Rule 2: same graph twice is a no-op
    got = await store.get(NAME)
    assert canon(got) == canon(reference(doc))


# --- merge matrix: each case equals the in-memory union -----------------------------

async def test_rule2_anonymous_merge_with_nested_union(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* knows -> Ify\n  * since: 2018\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* knows -> Ify\n  * strength: close\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    knows = list(got[CHUKS].traverse(KNOWS))
    assert len(knows) == 1
    assert {str(p.label) for p in knows[0].properties} == {
        'https://schema.org/since', 'https://schema.org/strength'}


async def test_rule2_distinct_values_stay_distinct(store):
    doc = DOCHEADER + '\n# Chuks [Person]\n\n* nickname: Chuk\n* nickname: CK\n'
    await store.put(NAME, parse(doc))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(doc))
    vals = {p.value for p in got[CHUKS].getprop('https://schema.org/nickname')}
    assert vals == {'Chuk', 'CK'}


async def test_rule1_same_id_merges(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: a1\n  * note: from-A\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: a1\n  * note: from-B\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    props = list(got[CHUKS].getprop(AGE))
    assert len(props) == 1 and props[0].id is not None


async def test_rule1_skeleton_mismatch_errors(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: a1\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 29\n  * @id: a1\n'
    await store.put(NAME, parse(a))
    with pytest.raises(GraphMergeError):
        await store.put(NAME, parse(b))


async def test_rule3_identified_and_anonymous_distinct(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: canonical-age\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    props = list(got[CHUKS].getprop(AGE))
    assert len(props) == 2
    assert sum(1 for p in props if p.id is not None) == 1


async def test_interp_equal_merges(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    assert len(list(got[CHUKS].getprop(AGE))) == 1


async def test_interp_one_sided_adoption(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    props = list(got[CHUKS].getprop(AGE))
    assert len(props) == 1
    assert str(props[0].interp) == 'http://purl.org/onya/vocab/interp/number'


async def test_interp_conflicting_stay_distinct(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: text\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b))
    interps = {str(p.interp) for p in got[CHUKS].getprop(AGE)}
    assert interps == {'http://purl.org/onya/vocab/interp/number',
                       'http://purl.org/onya/vocab/interp/text'}


async def test_interp_same_id_conflict_errors(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: a1\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @id: a1\n  * @as: text\n'
    await store.put(NAME, parse(a))
    with pytest.raises(GraphMergeError):
        await store.put(NAME, parse(b))


async def test_interp_null_adopts_nothing_under_ambiguity(store):
    a = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: number\n'
    b = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n  * @as: text\n'
    c = DOCHEADER + '\n# Chuks [Person]\n\n* age: 28\n'
    await store.put(NAME, parse(a))
    await store.put(NAME, parse(b))
    await store.put(NAME, parse(c))               # contract-free, skeleton already ambiguous
    got = await store.get(NAME)
    assert canon(got) == canon(reference(a, b, c))
    props = list(got[CHUKS].getprop(AGE))
    assert len(props) == 2
    assert all(p.interp is not None for p in props)


# --- id-space collision -------------------------------------------------------------

async def test_id_space_collision_raises(store):
    g = graph()
    g.node('http://e.o/X')                        # a node id ...
    n = g.node('http://e.o/N')
    p = n.add_property('http://s/age', '28')
    g.register_assertion_id('http://e.o/X', p)    # ... reused as an assertion @id
    with pytest.raises(AssertionIdConflict):
        await store.put(NAME, g)


# --- catalog operations -------------------------------------------------------------

async def test_names_and_drop_and_missing(store):
    await store.put('http://e.o/g1', parse(DOCHEADER + '\n# A [Person]\n\n* age: 1\n'))
    await store.put('http://e.o/g2', parse(DOCHEADER.replace('http://e.o/doc', 'http://e.o/g2')
                                            + '\n# B [Person]\n\n* age: 2\n'))
    names = {str(n) async for n in store.names()}
    assert {'http://e.o/g1', 'http://e.o/g2'} <= names

    with pytest.raises(KeyError):
        await store.get('http://e.o/missing')

    await store.drop('http://e.o/g1')
    names_after = {str(n) async for n in store.names()}
    assert 'http://e.o/g1' not in names_after and 'http://e.o/g2' in names_after

    with pytest.raises(KeyError):
        await store.drop('http://e.o/g1')          # already gone


async def test_named_graphs_are_isolated(store):
    g1doc = DOCHEADER.replace('http://e.o/doc', 'http://e.o/g1') + '\n# Chuks [Person]\n\n* age: 28\n'
    g2doc = DOCHEADER.replace('http://e.o/doc', 'http://e.o/g2') + '\n# Chuks [Person]\n\n* age: 99\n'
    await store.put('http://e.o/g1', parse(g1doc))
    await store.put('http://e.o/g2', parse(g2doc))
    # a merge into g2 must not touch g1
    await store.put('http://e.o/g2', parse(g2doc.replace('* age: 99', '* age: 99\n* height: 180')))
    g1 = await store.get('http://e.o/g1')
    assert {p.value for p in g1[CHUKS].getprop(AGE)} == {'28'}
    assert not list(g1[CHUKS].getprop('https://schema.org/height'))
