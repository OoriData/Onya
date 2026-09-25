# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.query
'''
Entry-point lookup: "which node is the user talking about?"

`search()` ranks nodes by how well one of their property values matches a human-typed,
possibly partial, misspelled, or differently-cased query. It is name/label lookup, not a
query language and not full-text relevance (no stemming, no tf-idf).

Ranking is tiered, strongest first, over *normalized* strings (see `normalize`):

- `exact`  — the value equals the query;
- `prefix` — the value starts with the query, ending at a word boundary
  (`ada` is a prefix of `Ada Lovelace`, but not of `Adah Isaacs Menken`);
- `word`   — the query occurs as whole words inside the value (`king` in `Augusta Ada King`);
- `fuzzy`  — similarity ≥ `min_score`.

Similarity (the fuzzy test, and the tiebreak score within `prefix`/`word`) is pluggable via
`similarity=`:

- `'difflib'` (default) — stdlib `difflib.SequenceMatcher.ratio()`; no dependency, and the
  same results on every install.
- `'rapidfuzz'` — `rapidfuzz`'s normalized Indel similarity (`pip install "onya[fuzzy]"`),
  ~40x faster. It is a true longest-common-subsequence measure, so it scores the same or a
  little *higher* than difflib's Ratcliff/Obershelp matching (mean +0.03, up to +0.33 on
  scrambled strings): fuzzy-tier membership near `min_score` and fuzzy-tier order can differ
  from the default. Opt-in by name rather than auto-detected, so results never silently
  depend on what happens to be installed.
- any callable `(normalized_query, normalized_value) -> float` in [0, 1].

Tier is the primary sort key and `score` only breaks ties within a tier, so a strong-tier
hit is never outranked by a slightly higher fuzzy score. The result is a ranked list; whether
the top hit is unambiguous is the caller's call (`SearchHit.is_clear_winner` helps).

The scoring core (`score_value`, `rank`) is shared with the store backends that rank
in-process, so an in-memory search and a SQLite/file store search give the same results.
PostgreSQL computes the same tiers in SQL but scores with `pg_trgm` trigram similarity, so its
fuzzy *scores* differ (see `onya.store.base.SearchStore`).
'''

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from amara.iri import I

from onya.terms import ONYA_INTERP

__all__ = ['SearchHit', 'search', 'normalize', 'score_value', 'rank', 'resolve_similarity',
           'difflib_similarity', 'rapidfuzz_similarity', 'TIERS', 'DEFAULT_MIN_SCORE']

TIERS = ('exact', 'prefix', 'word', 'fuzzy')  # strongest first
_TIER_RANK = {t: i for i, t in enumerate(TIERS)}
DEFAULT_MIN_SCORE = 0.5
TEXT_INTERP = ONYA_INTERP('text')

_NON_ALNUM = re.compile(r'[\W_]+')


def normalize(s: str) -> str:
    '''Default normalization: casefold, then collapse runs of non-alphanumerics to one space.'''
    return _NON_ALNUM.sub(' ', s.casefold()).strip()


def difflib_similarity(a: str, b: str) -> float:
    '''Default similarity: stdlib `SequenceMatcher.ratio()` (autojunk off, so it's order-stable).'''
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def rapidfuzz_similarity(a: str, b: str) -> float:
    '''`rapidfuzz` normalized Indel similarity; requires `pip install "onya[fuzzy]"`.'''
    try:
        from rapidfuzz.distance import Indel
    except ImportError as e:
        raise ImportError('similarity="rapidfuzz" requires: pip install "onya[fuzzy]"') from e
    return Indel.normalized_similarity(a, b)


Similarity = Callable[[str, str], float]
_NAMED_SIMILARITY = {'difflib': difflib_similarity, 'rapidfuzz': rapidfuzz_similarity}


def resolve_similarity(similarity: str | Similarity | None) -> Similarity:
    '''Map `None`/`'difflib'`/`'rapidfuzz'`/a callable to a similarity function.'''
    if similarity is None:
        return difflib_similarity
    if callable(similarity):
        return similarity
    try:
        fn = _NAMED_SIMILARITY[similarity]
    except KeyError:
        raise ValueError(f'Unknown similarity {similarity!r}; expected one of {sorted(_NAMED_SIMILARITY)} '
                         'or a callable') from None
    if fn is rapidfuzz_similarity:
        rapidfuzz_similarity('', '')  # fail fast with the install hint, not mid-search
    return fn


def _fuzzy(q: str, v: str, sim: Similarity) -> float:
    '''
    Similarity of query to value: the better of the whole-string score and the best score
    against any window of the value with as many words as the query — so a short query is
    compared with the part of a long value it might name, not diluted by the rest of it.
    '''
    best = sim(q, v)
    qn = q.count(' ') + 1
    vt = v.split(' ')
    if len(vt) > qn:
        for i in range(len(vt) - qn + 1):
            best = max(best, sim(q, ' '.join(vt[i:i + qn])))
    return best


def score_value(q: str, v: str, min_score: float = DEFAULT_MIN_SCORE,
                similarity: Similarity = difflib_similarity) -> tuple[str, float] | None:
    '''
    Classify already-normalized value `v` against normalized query `q`, returning
    `(tier, score)` or None for no match. Within the `prefix`/`word` tiers the score is the
    whole-string similarity (so the closer-length value ranks first); `exact` scores 1.0.
    '''
    if not q or not v:
        return None
    if v == q:
        return ('exact', 1.0)
    if v.startswith(q + ' '):
        return ('prefix', similarity(q, v))
    if f' {q} ' in f' {v} ':
        return ('word', similarity(q, v))
    score = _fuzzy(q, v, similarity)
    if score >= min_score:
        return ('fuzzy', score)
    return None


@dataclass(frozen=True)
class SearchHit:
    '''
    One ranked match: the node (by id; plus the node object itself for an in-memory search),
    the assertion that matched (`label`, `value`, and the property object in memory), its tier,
    and its score within that tier.

    `score` is in [0, 1] and is only comparable between hits from the same search: it depends
    on the similarity measure (`difflib` by default; `rapidfuzz` if chosen) and, for a
    PostgreSQL store search, is `pg_trgm` trigram similarity rather than either. `tier` is
    the backend-independent part.
    '''
    node_id: I | str
    label: I | str
    value: str
    tier: str
    score: float
    node: object = None       # onya.graph.node, in-memory searches only
    assertion: object = None  # onya.graph.property_, in-memory searches only

    @property
    def sort_key(self) -> tuple:
        # Tier first, score within tier, then a deterministic tiebreak (sets have no order).
        return (_TIER_RANK[self.tier], -self.score, str(self.node_id), str(self.label), self.value)

    @staticmethod
    def is_clear_winner(hits: list['SearchHit'], margin: float = 0.1) -> bool:
        '''
        True if `hits[0]` stands clear of the runner-up: it is the only hit, or it is in a
        stronger tier, or it leads within the same tier by at least `margin`. A convenience
        for the "use the top hit, mention the runners-up" pattern; ambiguity policy stays
        with the caller.
        '''
        if not hits:
            return False
        if len(hits) == 1:
            return True
        top, second = hits[0], hits[1]
        if _TIER_RANK[top.tier] < _TIER_RANK[second.tier]:
            return True
        return top.score - second.score >= margin


def rank(hits: Iterable[SearchHit], *, per_node: bool = True, limit: int | None = None) -> list[SearchHit]:
    '''Sort scored hits strongest first, keep each node's best when `per_node`, and truncate.'''
    ordered = sorted(hits, key=lambda h: h.sort_key)
    if per_node:
        seen: set = set()
        best = []
        for h in ordered:
            if h.node_id not in seen:
                seen.add(h.node_id)
                best.append(h)
        ordered = best
    return ordered if limit is None else ordered[:limit]


def score_candidates(query: str, candidates: Iterable[tuple], *, min_score: float = DEFAULT_MIN_SCORE,
                     normalize: Callable[[str], str] = normalize,
                     similarity: str | Similarity | None = None) -> Iterable[SearchHit]:
    '''
    Score `(node_id, label, value, node_obj, assertion_obj)` candidates against `query`,
    yielding a `SearchHit` for each that matches. The shared in-process path for stores.
    '''
    sim = resolve_similarity(similarity)
    q = normalize(query)
    if not q:
        return
    for node_id, label, value, node_obj, assertion_obj in candidates:
        scored = score_value(q, normalize(value), min_score, sim)
        if scored is not None:
            yield SearchHit(node_id, label, value, scored[0], scored[1], node_obj, assertion_obj)


def search(g, query: str, *, labels: Iterable[I | str] | None = None, types: Iterable[I | str] | None = None,
           limit: int | None = None, min_score: float = DEFAULT_MIN_SCORE, per_node: bool = True,
           normalize: Callable[[str], str] = normalize,
           similarity: str | Similarity | None = None) -> list[SearchHit]:
    '''
    Rank the nodes of graph `g` by how well one of their (first-level) property values
    matches `query`.

    - `labels`: the properties to search, each a full IRI, CURIE, or bare name resolved
      against `g.prefixes`. Default: every property whose interpretation (`@as`) is absent
      or `text` — numbers, dates, IRIs etc. are not names.
    - `types`: only nodes carrying at least one of these types (IRI/CURIE/bare name).
    - `limit`: at most this many hits; `min_score`: the fuzzy-tier threshold (0-1).
    - `per_node`: one hit per node, its best-ranked assertion (default); False returns every
      matching assertion.
    - `normalize`: replaces the default casefold + non-alphanumeric collapsing.
    - `similarity`: `'difflib'` (default), `'rapidfuzz'`, or a callable; see the module docstring.
    '''
    sim = resolve_similarity(similarity)  # validate up front, before any work
    label_set = None if labels is None else {g.resolve(lbl) for lbl in labels}
    type_set = None if types is None else {g.resolve(t) for t in types}

    def candidates():
        for n in g.nodes.values():
            if type_set is not None and not (n.types & type_set):
                continue
            for p in n.properties:
                if label_set is not None:
                    if p.label not in label_set:
                        continue
                elif p.interp is not None and p.interp != TEXT_INTERP:
                    continue
                yield (n.id, p.label, p.value, n, p)

    hits = score_candidates(query, candidates(), min_score=min_score, normalize=normalize, similarity=sim)
    return rank(hits, per_node=per_node, limit=limit)
