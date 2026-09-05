# -*- coding: utf-8 -*-
# test/store/test_store_overlay_conflict.py
'''
Behavioral tests for ``OverlayReadStore.overlay()`` (precedence-based conflict resolution
across named graphs; see issue #38). Runs against every backend from the ``store`` fixture
that offers the ``OverlayReadStore`` capability — SQLite always, PostgreSQL when
``ONYA_TEST_PG_DSN`` is set; the filesystem backend is skipped.

    pytest -s test/store/test_store_overlay_conflict.py
'''

import pytest

from onya.store import OverlayReadStore
from onya.graph import GraphMergeError

from store_helpers import put_each


@pytest.fixture(autouse=True)
def _require_overlay_store(store):
    if not isinstance(store, OverlayReadStore):
        pytest.skip('backend does not offer the OverlayReadStore capability')


AGE = 'https://schema.org/age'
EMAIL = 'https://schema.org/email'
VALUE = 'https://schema.org/value'
CONFIDENCE = 'https://schema.org/confidence'

DOC_A = '''\
# @docheader

* @document: http://e.o/overlayA
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* age: 28
* email: a@example.org
'''

DOC_B = '''\
# @docheader

* @document: http://e.o/overlayB
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* age: 31
* email: b@example.org
'''


def _values(g, label):
    return sorted(p.value for p in g['http://e.o/Chuks'].properties if str(p.label) == label)


# --- no cardinality hints: reduces to union()'s keep-everything behavior -------------

async def test_no_single_cardinality_keeps_everything(store):
    names = await put_each(store, DOC_A, DOC_B)
    g, conflicts = await store.overlay(names)
    assert _values(g, AGE) == ['28', '31']
    assert conflicts == []


# --- single_cardinality: polymorphic predicate ---------------------------------------

async def test_single_cardinality_as_a_set_shadows_only_listed_labels(store):
    names = await put_each(store, DOC_A, DOC_B)
    g, conflicts = await store.overlay(names, single_cardinality={AGE}, precedence=names)
    assert _values(g, AGE) == ['28']              # shadowed to the precedence winner
    assert _values(g, EMAIL) == ['a@example.org', 'b@example.org']  # untouched
    assert len(conflicts) == 1
    assert str(conflicts[0].label) == AGE


async def test_single_cardinality_as_a_callable(store):
    names = await put_each(store, DOC_A, DOC_B)
    g, conflicts = await store.overlay(names, single_cardinality=lambda label: str(label) == AGE,
                                       precedence=names)
    assert _values(g, AGE) == ['28']
    assert len(conflicts) == 1


# --- precedence order decides the winner ----------------------------------------------

async def test_precedence_order_decides_winner(store):
    names = await put_each(store, DOC_A, DOC_B)
    g, _ = await store.overlay(names, single_cardinality={AGE}, precedence=list(reversed(names)))
    assert _values(g, AGE) == ['31']   # docB now wins


# --- ShadowedConflict reports the audit trail, key_values included -------------------

async def test_shadowed_conflict_reports_winner_and_losers(store):
    names = await put_each(store, DOC_A, DOC_B)
    g, conflicts = await store.overlay(names, single_cardinality={AGE}, precedence=names)
    (c,) = conflicts
    assert c.winner.payload == '28'
    assert [loser.payload for loser in c.losers] == ['31']
    assert set(c.key_values) == {c.winner.graph_names, *[loser.graph_names for loser in c.losers]}


# --- custom key: arbitrary logic, "be like Python sorting" ---------------------------

async def test_custom_key_overrides_precedence(store):
    names = await put_each(store, DOC_A, DOC_B)

    def prefer_higher_age(candidate):
        return float(candidate.payload)

    g, conflicts = await store.overlay(names, single_cardinality={AGE},
                                       precedence=names, key=prefer_higher_age)
    assert _values(g, AGE) == ['31']   # custom key beats precedence order entirely


# --- @id (Rule 1) conflicts: overlay always resolves, never raises -------------------

async def test_identified_conflict_never_raises_and_resolves_via_precedence(store):
    doc_x = '''\
# @docheader

* @document: http://e.o/overlayX
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* knows -> Ify
  * @id: overlay-friendship
'''
    doc_y = '''\
# @docheader

* @document: http://e.o/overlayY
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Chuks [Person]

* knows -> Obi
  * @id: overlay-friendship
'''
    names = await put_each(store, doc_x, doc_y)

    with pytest.raises(GraphMergeError):
        await store.union(names)   # union() still raises -- unchanged

    g, conflicts = await store.overlay(names, precedence=names)   # no single_cardinality needed
    targets = [str(e.target.id) for e in g['http://e.o/Chuks'].edges]
    assert targets == ['http://e.o/Ify']
    assert len(conflicts) == 1


# --- prefer_confidence: overrides precedence when a candidate has @confidence --------

async def test_prefer_confidence_overrides_precedence(store):
    doc_conf_a = '''\
# @docheader

* @document: http://e.o/overlayConfA
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Filing [Thing]

* value: "100"
'''
    doc_conf_b = '''\
# @docheader

* @document: http://e.o/overlayConfB
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Filing [Thing]

* value: "200"
    * @method -> NerTag
        * @confidence: 0.95
'''
    names = await put_each(store, doc_conf_a, doc_conf_b)

    # precedence alone would pick docConfA ("100"); prefer_confidence should override it
    g, conflicts = await store.overlay(names, single_cardinality={VALUE},
                                       precedence=names, prefer_confidence=True)
    values = [p.value for p in g['http://e.o/Filing'].properties if str(p.label) == VALUE]
    assert values == ['200']
    assert conflicts[0].winner.confidence == 0.95
    assert conflicts[0].losers[0].confidence is None


async def test_prefer_confidence_false_ignores_confidence(store):
    '''prefer_confidence is a call flag -- default False means precedence alone decides.'''
    doc_conf_a = '''\
# @docheader

* @document: http://e.o/overlayConfA2
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Filing [Thing]

* value: "100"
'''
    doc_conf_b = '''\
# @docheader

* @document: http://e.o/overlayConfB2
* @nodebase: http://e.o/
* @schema: https://schema.org/

# Filing [Thing]

* value: "200"
    * @method -> NerTag
        * @confidence: 0.95
'''
    names = await put_each(store, doc_conf_a, doc_conf_b)
    g, _ = await store.overlay(names, single_cardinality={VALUE}, precedence=names)  # prefer_confidence=False
    values = [p.value for p in g['http://e.o/Filing'].properties if str(p.label) == VALUE]
    assert values == ['100']   # precedence wins despite docB's higher confidence


# --- error handling: same contract as union() -----------------------------------------

async def test_overlay_empty_names_raises_value_error(store):
    with pytest.raises(ValueError):
        await store.overlay([])


async def test_overlay_unknown_name_raises_key_error(store):
    names = await put_each(store, DOC_A)
    with pytest.raises(KeyError):
        await store.overlay(names + ['http://e.o/does-not-exist'])
