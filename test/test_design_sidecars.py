# -*- coding: utf-8 -*-
# test/test_design_sidecars.py
'''
The examples in doc/design-sidecars.md work: every Onya Literate block parses, and the
`transform` sketch moves what it says it moves, flags what it can't decide, and is idempotent.

    pytest -s test/test_design_sidecars.py
'''

import io
import re
import warnings
from pathlib import Path

import pytest

from onya.serial import literate

DOC = Path(__file__).resolve().parent.parent / 'doc' / 'design-sidecars.md'
TEXT = DOC.read_text(encoding='utf-8')
HEADER = ('# @docheader\n* @document: https://example.org/kg/doc\n* @nodebase: https://example.org/kg/\n'
          '* @schema: https://schema.org/\n* @iri:\n    * ex: https://example.org/vocab\n\n')
NS = 'https://example.org/vocab/'
ACME = 'https://example.org/kg/acme'

BLOCKS = re.findall(r'```\n(#.*?)```', TEXT, re.S)
PYTHON = re.findall(r'```python\n(.*?)```', TEXT, re.S)


@pytest.fixture(scope='module')
def code():
    ns = {}
    for block in PYTHON:
        if 'def transform' in block or 'def copy_of' in block:
            exec(block, ns)
    return ns


def parse(*blocks):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return literate.read(HEADER + '\n'.join(blocks))


@pytest.mark.parametrize('block', BLOCKS, ids=[b.split('\n', 1)[0][:40] for b in BLOCKS])
def test_example_parses(block):
    parse(block)


def test_transform_moves_and_is_idempotent(code):
    r = parse(BLOCKS[0])  # the "before" node
    g = r.graph
    rows, review = code['transform'](g, NS)
    assert not review
    assert {(t, s, row['predicate']) for t, s, row in rows} == {
        ('billing_terms', ACME, 'fee'), ('billing_terms', ACME, 'description'),
        ('decision_log', ACME, 'resolution')}
    out = io.StringIO()
    literate.write(g, out, document=r.doc_iri, schema=r.schema, nodebase=r.nodebase, prefixes=r.prefixes)
    text = out.getvalue()
    assert '$' not in text and '[amount on file]' in text and 'ex:note' in text
    assert code['transform'](g, NS) == ([], [])  # second pass changes nothing


def test_transform_flags_what_it_cannot_decide(code):
    g = parse('# c [Organization]\n* <ex:status>: paused pending budget\n'
              '* <ex:fee>: $5k [=c-fee]\n').graph
    rows, review = code['transform'](g, NS)
    assert not rows and len(review) == 2


def test_copy_of_is_faithful(code):
    r = parse(BLOCKS[0])
    dup = code['copy_of'](r.graph, r)
    code['transform'](dup, NS)
    assert any('$' in p.value for p in r.graph[ACME].properties)  # original untouched
