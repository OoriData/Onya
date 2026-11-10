# -*- coding: utf-8 -*-
# test/test_graph_drop_document.py
'''
`drop_document_nodes`: remove the `onya:Document` nodes a read mints, keeping any that carry real assertions.

    pytest -s test/test_graph_drop_document.py
'''

from onya.digest import digest
from onya.graph import drop_document_nodes
from onya.serial.literate import read, read_many
from onya.store import connect
from onya.terms import ONYA_DOCUMENT

DOC = 'http://e.o/doc'
PLAIN = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# chuks [Person]
* name: Chuks
'''
TITLED = PLAIN.replace('* @schema: http://e.o/\n', '* @schema: http://e.o/\n* title: A titled graph\n')


def docs(g):
    return [str(n.id) for n in g.nodes.values() if ONYA_DOCUMENT in n.types]


def test_a_bare_document_node_is_removed_and_nothing_else():
    r = read(PLAIN)
    assert docs(r.graph) == [DOC]
    assert drop_document_nodes(r.graph) == [DOC]
    assert docs(r.graph) == [] and 'http://e.o/chuks' in r.graph
    assert r.doc_iri == DOC  # the parse result still says which document it read


def test_every_document_of_a_read_many_goes(tmp_path):
    (tmp_path / 'a.onya').write_text(PLAIN)
    (tmp_path / 'b.onya').write_text(PLAIN.replace('e.o/doc', 'e.o/doc2').replace('chuks', 'ify'))
    g = read_many(str(tmp_path), merge=True).graph
    assert len(docs(g)) == 2
    assert sorted(drop_document_nodes(g)) == ['http://e.o/doc', 'http://e.o/doc2']
    assert docs(g) == [] and {'http://e.o/chuks', 'http://e.o/ify'} <= {str(i) for i in g.nodes}


def test_a_document_node_with_assertions_of_its_own_stays_unless_forced():
    g = read(TITLED).graph
    assert [str(p.value) for p in g[DOC].properties] == ['A titled graph']  # the docheader's own metadata
    assert drop_document_nodes(g) == [] and docs(g) == [DOC]
    assert drop_document_nodes(g, force=True) == [DOC] and docs(g) == []


def test_a_document_node_that_an_edge_points_at_stays_unless_forced():
    g = read(PLAIN.replace('* name: Chuks\n', '* name: Chuks\n* describedBy -> doc\n')).graph
    assert list(g.inbound(DOC))  # removing the node would leave this edge aimed at an undeclared target
    assert drop_document_nodes(g) == [] and docs(g) == [DOC]
    assert drop_document_nodes(g, force=True) == [DOC]
    assert DOC in g.dangling() and len(list(g.inbound(DOC))) == 1  # the edge stays, aimed at an undeclared node


def test_an_at_source_assertion_does_not_keep_the_node():
    g = read(PLAIN, document_source_assertions=True).graph  # @source holds the document's IRI as a value, not an edge
    assert drop_document_nodes(g) == [DOC]


def test_the_digest_is_unchanged():
    g = read(PLAIN).graph
    before = digest(g)
    drop_document_nodes(g)
    assert digest(g) == before


def test_a_graph_read_back_from_a_store_loses_its_document_node_too(tmp_path):
    import asyncio

    async def roundtrip():
        async with await connect(f'sqlite:{tmp_path}/kg.db') as st:
            await st.put(DOC, read(PLAIN).graph)
            return await st.get(DOC)

    g = asyncio.run(roundtrip())
    assert docs(g) == [DOC]  # the store kept it
    assert drop_document_nodes(g) == [DOC]


def test_it_is_a_no_op_on_a_graph_without_document_nodes():
    g = read(PLAIN).graph
    drop_document_nodes(g)
    assert drop_document_nodes(g) == []
