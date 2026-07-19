# -*- coding: utf-8 -*-
# test/store/test_store_convention.py
'''
Filesystem-backend fidelity: a store round trip preserves an authored file's namespace
convention (so ``materialize -> serialize -> commit -> re-seed`` keeps git diffs compact and
reviewable) while staying a faithful graph union. Filesystem-specific: it inspects the emitted
``.onya`` text, which SQL backends do not produce.

    pytest -s test/store/test_store_convention.py
'''

from onya.graph import graph
from onya.serial.literate import LiterateParser, read
from onya.store.filesystem import FileStore, _slug


NAME = 'https://example.org/kb/doc'

SEED = '''# @docheader
* @document: https://example.org/kb/doc
* @nodebase: https://example.org/kb/
* @schema: https://example.org/vocab/

# Widget [Product]
* title: Sprocket
* sku: "0042"
'''

ADD = '''# @docheader
* @document: https://example.org/kb/doc
* @nodebase: https://example.org/kb/
* @schema: https://example.org/vocab/

# Widget [Product]
* color: red

# Gadget [Product]
* title: Gizmo
'''

_reader = LiterateParser(warn_empty_blocks=False)


def _triples(g):
    out = set()
    for nid, node in g.nodes.items():
        for t in node.types:
            out.add(('T', str(nid), str(t)))
        for p in node.properties:
            out.add(('P', str(nid), str(p.label), str(p.value)))
    return out


async def test_put_merge_preserves_authored_convention(tmp_path):
    '''A committed seed file with @schema/@nodebase keeps its compact form across put(merge).'''
    root = tmp_path / 'graphs'
    root.mkdir()
    seed_path = root / f'{_slug(NAME)}.onya'
    seed_path.write_text(SEED)  # simulate a git-checked-out authored seed

    store = FileStore(root)
    add_g = graph(); read(ADD, add_g)
    await store.put(NAME, add_g, merge=True)

    text = seed_path.read_text()
    # Convention preserved: docheader intact, names stay compact (bare, not <full-iri>).
    assert '* @schema: https://example.org/vocab/' in text
    assert '* @nodebase: https://example.org/kb/' in text
    assert any(ln.strip() in ('* title: Sprocket', '* title: Gizmo') for ln in text.splitlines())
    assert '<https://example.org/vocab/title>' not in text  # not fallen back to explicit

    # Faithful union with no mashed IRIs.
    got = graph(); _reader.parse(text, got)
    tr = _triples(got)
    assert ('P', 'https://example.org/kb/Widget', 'https://example.org/vocab/title', 'Sprocket') in tr
    assert ('P', 'https://example.org/kb/Widget', 'https://example.org/vocab/color', 'red') in tr
    assert ('P', 'https://example.org/kb/Gadget', 'https://example.org/vocab/title', 'Gizmo') in tr
    assert not any('vocabtitle' in t[2] or 'vocabcolor' in t[2] for t in tr)


async def test_new_graph_without_seed_uses_explicit_form(tmp_path):
    '''With no prior file, the store falls back to the faithful explicit-IRI form (unchanged).'''
    root = tmp_path / 'graphs'
    root.mkdir()
    store = FileStore(root)
    g = graph(); read(SEED, g)
    await store.put(NAME, g, merge=True)

    text = (root / f'{_slug(NAME)}.onya').read_text()
    assert '@schema' not in text                            # no convention to preserve
    assert '<https://example.org/vocab/title>' in text      # explicit, still faithful
    got = graph(); _reader.parse(text, got)
    assert _triples(got) == _triples(g)
