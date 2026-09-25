# -*- coding: utf-8 -*-
# test/test_query_search.py
'''
Ranked entry-point search (`onya.query.search` / `graph.search`): tiers, normalization,
filters, per-node collapsing, and the clear-winner helper.

    pytest -s test/test_query_search.py
'''

import pytest

from onya.graph import UnknownPrefixError
from onya.query import SearchHit, normalize, score_value
from onya.serial import literate

PEOPLE = 'http://example.org/people/'
SCHEMA = 'https://schema.org/'

DOC = '''# @docheader
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# ada [Person]
* name: Ada Lovelace
* alternateName: Augusta Ada King
* worksFor -> analytical-engine-co

# adah [Person]
* name: Adah Isaacs Menken

# babbage [Person]
* name: Charles Babbage
* birthDate: 1791
    * @as: number
* worksFor -> analytical-engine-co

# analytical-engine-co [Organization]
* name: Analytical Engine Company
'''


@pytest.fixture
def g():
    return literate.read(DOC).graph


def ids(hits):
    return [str(h.node_id).removeprefix(PEOPLE) for h in hits]


def test_normalize():
    assert normalize('  Ada  LOVELACE!! ') == 'ada lovelace'
    assert normalize('Lovelace, Ada (née Byron)') == 'lovelace ada née byron'
    assert normalize('snake_case-name') == 'snake case name'


def test_score_value_tiers():
    assert score_value('ada lovelace', 'ada lovelace') == ('exact', 1.0)
    assert score_value('ada', 'ada lovelace')[0] == 'prefix'
    assert score_value('ada', 'adah isaacs menken')[0] == 'fuzzy'  # not a word-boundary prefix
    assert score_value('king', 'augusta ada king')[0] == 'word'
    assert score_value('zzz', 'ada lovelace') is None
    assert score_value('', 'ada') is None


def test_fuzzy_misspelling_ranked(g):
    hits = g.search('ada lovelac', labels=['schema:name', 'schema:alternateName'])
    assert ids(hits) == ['ada', 'adah']
    top = hits[0]
    assert top.tier == 'fuzzy' and top.score > 0.9
    assert top.label == SCHEMA + 'name' and top.value == 'Ada Lovelace'
    assert top.node is g[PEOPLE + 'ada'] and top.assertion.value == 'Ada Lovelace'


def test_prefix_tier_outranks_higher_fuzzy_score(g):
    hits = g.search('ada', labels=['schema:name'])
    assert ids(hits) == ['ada', 'adah']
    assert [h.tier for h in hits] == ['prefix', 'fuzzy']
    assert hits[1].score > hits[0].score  # tier, not score, decides


def test_word_tier_and_type_filter(g):
    hits = g.search('king', labels=['schema:name', 'schema:alternateName'], types=['schema:Person'])
    assert ids(hits) == ['ada']
    assert hits[0].tier == 'word' and hits[0].label == SCHEMA + 'alternateName'
    assert g.search('analytical', types=['Person']) == []
    assert ids(g.search('analytical', types=['Organization'])) == ['analytical-engine-co']


def test_exact_is_case_and_punctuation_insensitive(g):
    hits = g.search('CHARLES   babbage!')
    assert hits[0].tier == 'exact' and ids(hits)[:1] == ['babbage']


def test_default_labels_skip_non_text_interps(g):
    assert g.search('1791') == []                      # @as: number is not a name
    assert ids(g.search('1791', labels=['birthDate'])) == ['babbage']  # unless asked for


def test_per_node_and_limit(g):
    one = g.search('ada')
    assert len(ids(one)) == len(set(ids(one)))
    every = g.search('ada', per_node=False)
    ada_hits = [h for h in every if h.node_id == PEOPLE + 'ada']
    assert {h.label for h in ada_hits} == {SCHEMA + 'name', SCHEMA + 'alternateName'}
    assert len(g.search('ada', limit=1)) == 1


def test_min_score(g):
    assert ids(g.search('ada lovelac', labels=['name'], min_score=0.9)) == ['ada']


def test_custom_normalize(g):
    # A normalizer that ignores everything but consonants makes a vowel-garbled query exact.
    def consonants(s):
        return ''.join(c for c in s.casefold() if c.isalpha() and c not in 'aeiou')
    hits = g.search('Chorlos Bebbege', labels=['name'], normalize=consonants)
    assert hits[0].tier == 'exact' and ids(hits)[:1] == ['babbage']


def test_unknown_prefix_in_labels_raises(g):
    with pytest.raises(UnknownPrefixError):
        g.search('ada', labels=['ex:name'])


def test_similarity_callable_and_bad_name(g):
    calls = []

    def always_half(q, v):
        calls.append((q, v))
        return 0.5
    hits = g.search('zzz', labels=['name'], similarity=always_half)
    assert calls and {h.tier for h in hits} == {'fuzzy'} and {h.score for h in hits} == {0.5}
    with pytest.raises(ValueError, match='Unknown similarity'):
        g.search('ada', similarity='levenshtein')


def test_rapidfuzz_similarity(g):
    pytest.importorskip('rapidfuzz')
    hits = g.search('ada lovelac', labels=['name'], similarity='rapidfuzz')
    assert ids(hits)[0] == 'ada' and hits[0].tier == 'fuzzy'
    # Same tiers as the default for non-fuzzy matches; LCS-based scores are never lower.
    assert [h.tier for h in g.search('ada', labels=['name'], similarity='rapidfuzz')][:1] == ['prefix']
    d = {h.node_id: h.score for h in g.search('ada lovelac', labels=['name'])}
    r = {h.node_id: h.score for h in hits}
    assert all(r[k] >= d[k] - 1e-9 for k in d)


def test_is_clear_winner():
    def hit(tier, score, nid='x'):
        return SearchHit(nid, 'l', 'v', tier, score)
    assert not SearchHit.is_clear_winner([])
    assert SearchHit.is_clear_winner([hit('fuzzy', 0.6)])
    assert SearchHit.is_clear_winner([hit('prefix', 0.4), hit('fuzzy', 0.9)])
    assert not SearchHit.is_clear_winner([hit('fuzzy', 0.80), hit('fuzzy', 0.75)])
    assert SearchHit.is_clear_winner([hit('fuzzy', 0.80), hit('fuzzy', 0.75)], margin=0.05)
