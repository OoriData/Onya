# -*- coding: utf-8 -*-
# test/store/test_store_relational.py
'''
Unit tests for the shared relational core: skeleton hash v1 vectors, the origin-key rules
for nested assertions, the pure interp-amendment decision, and the schema version gate.

    pytest -s test/store/test_store_relational.py
'''

import sqlite3

import pytest

from onya.graph import graph
from onya.store import connect
from onya.store.exceptions import UnknownSchemaVersion
from onya.store._relational import (
    SQLITE, classify_anonymous, ensure_schema, hexhash, iter_records, skeleton_hash,
)


# --- fixed skeleton-hash vectors (v1) -----------------------------------------------

def test_property_hash_vector():
    assert skeleton_hash('P', 'http://e.o/Chuks', 'https://schema.org/age', '28').hex() == (
        '640292f187ca45d47c73beb043f91a0e2f5b3f30731a5035d43031f9a07df9e3')


def test_edge_hash_vector():
    assert skeleton_hash('E', 'http://e.o/Chuks', 'https://schema.org/knows',
                         'http://e.o/Ify').hex() == (
        'b9cde201d81048a45ee3ee3b1ef274138822f007d02e69a4e62679941971a273')


def test_nested_under_identified_origin_key():
    # origin_key of a child under an identified assertion is the parent's explicit id
    assert skeleton_hash('P', 'http://e.o/a1', 'https://schema.org/note', 'x').hex() == (
        'ce5a90a0f1d5177dd676c41b27048255e666ee6695338321464a89ec8d52a653')


def test_nested_under_anonymous_origin_key():
    # origin_key of a child under an anonymous assertion is hex(parent skeleton_hash)
    parent = skeleton_hash('E', 'http://e.o/Chuks', 'https://schema.org/knows', 'http://e.o/Ify')
    assert skeleton_hash('P', hexhash(parent), 'https://schema.org/since', '2018').hex() == (
        '60aebc3705e5bbf02a00ae12c1dee2204b56080a5b743cd633964ae6122f03e3')


def test_hash_depends_on_origin_and_kind():
    a = skeleton_hash('P', 'http://e.o/A', 'l', 'v')
    b = skeleton_hash('P', 'http://e.o/B', 'l', 'v')      # different origin
    c = skeleton_hash('E', 'http://e.o/A', 'l', 'v')      # different kind
    assert a != b and a != c and b != c


# --- iter_records derives the right origin keys -------------------------------------

def test_iter_records_origin_keys():
    g = graph()
    n = g.node('http://e.o/Chuks')
    e = n.add_edge('https://schema.org/knows', g.node('http://e.o/Ify'))
    e.add_property('https://schema.org/since', '2018')             # nested under anonymous edge
    p = n.add_property('https://schema.org/age', '28')
    g.register_assertion_id('http://e.o/a1', p)
    p.add_property('https://schema.org/note', 'x')                 # nested under identified prop

    recs = {(r.kind, r.label): r for r in iter_records(n)}
    edge_sk = recs[('E', 'https://schema.org/knows')].skeleton
    since = recs[('P', 'https://schema.org/since')]
    note = recs[('P', 'https://schema.org/note')]

    # child of anonymous edge keyed by hex(parent hash); child of identified prop keyed by @id
    assert since.skeleton == skeleton_hash('P', hexhash(edge_sk), 'https://schema.org/since', '2018')
    assert note.skeleton == skeleton_hash('P', 'http://e.o/a1', 'https://schema.org/note', 'x')


# --- classify_anonymous (the interp amendment, pure) --------------------------------

NUM, TXT = 'iri:number', 'iri:text'


def test_classify_insert_when_empty():
    assert classify_anonymous([], None) == ('insert', None, None)
    assert classify_anonymous([], NUM) == ('insert', None, None)


def test_classify_equal_interp_merges():
    assert classify_anonymous([(1, NUM)], NUM) == ('merge', 1, None)
    assert classify_anonymous([(1, None)], None) == ('merge', 1, None)


def test_classify_contract_adopts_null_row():
    # incoming has a contract, an existing NULL row adopts it (one-sided)
    assert classify_anonymous([(1, None)], NUM) == ('merge', 1, NUM)


def test_classify_null_adopts_sole_contract():
    assert classify_anonymous([(1, NUM)], None) == ('merge', 1, None)


def test_classify_null_adopts_nothing_under_ambiguity():
    assert classify_anonymous([(1, NUM), (2, TXT)], None) == ('drop', None, None)


def test_classify_conflicting_contract_inserts():
    assert classify_anonymous([(1, NUM)], TXT) == ('insert', None, None)


# --- schema version gate ------------------------------------------------------------

async def test_unknown_schema_version_refused(tmp_path):
    path = f'{tmp_path}/v.db'
    async with await connect(f'sqlite:{path}'):
        pass  # creates the schema at version 1

    # tamper the recorded skeleton-hash version
    conn = sqlite3.connect(path)
    conn.execute("UPDATE onya_meta SET value = '99' WHERE key = 'skeleton_hash_version'")
    conn.commit()
    conn.close()

    with pytest.raises(UnknownSchemaVersion):
        await connect(f'sqlite:{path}')


def test_ensure_schema_direct_version_gate():
    conn = sqlite3.connect(':memory:')
    cur = conn.cursor()
    ensure_schema(cur, SQLITE)
    cur.execute("UPDATE onya_meta SET value = '2' WHERE key = 'schema_version'")
    with pytest.raises(UnknownSchemaVersion):
        ensure_schema(cur, SQLITE)
    conn.close()
