# -*- coding: utf-8 -*-
# test/test_skill_examples.py
'''
Every Onya Literate example in onya-graph.SKILL.md parses, and no comment text leaks into a
value. LLMs copy these examples, so a broken one propagates.

    pytest -s test/test_skill_examples.py
'''

import re
import warnings
from pathlib import Path

import pytest

from onya.serial import literate

SKILL = Path(__file__).resolve().parent.parent / 'onya-graph.SKILL.md'
HEADER = ('# @docheader\n* @nodebase: http://example.org/kb/\n* @schema: https://schema.org/\n'
          '* @iri:\n    * ex: http://example.org/vocab/\n\n')

# Unlabeled fences whose first line is a Literate header: `# @docheader` or `# NodeId [...]`
BLOCKS = [b for b in re.findall(r'```\n(#.*?)```', SKILL.read_text(encoding='utf-8'), re.S)
          if 'import ' not in b]


@pytest.mark.parametrize('block', BLOCKS, ids=[b.split('\n', 1)[0][:40] for b in BLOCKS])
def test_skill_example_parses(block):
    doc = block if block.startswith('# @docheader') else HEADER + block
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # e.g. empty-block warnings for bare edge targets
        g = literate.read(doc).graph
    leaked = [p.value for n in g.nodes.values() for p in n.properties if '<!--' in str(p.value)]
    assert not leaked


def test_found_the_examples():
    assert len(BLOCKS) >= 5
