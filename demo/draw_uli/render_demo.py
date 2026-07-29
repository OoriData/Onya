#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# demo/draw_uli/render_demo.py

'''
Demo script for the `draw_uli` renderer prototype (Onya issue #33): a theme-able, code-driven
graph illustration built on `onya.viz.nx` + matplotlib. Not a supported library API — see
`driver.py`'s module docstring and `README.md` in this directory for status.

Usage (from this directory, so the sibling `driver`/`uli_night`/`aquatic` modules resolve, and
matplotlib/networkx are on the interpreter — `pip install "onya[nx]" matplotlib`):
    cd demo/draw_uli
    python render_demo.py

Generates (gitignored, per demo/.gitignore — rerun to reproduce):
    render_uli_night.png   — the reference "Things Fall Apart" family graph, uli_night design
    render_aquatic.png     — the same graph, aquatic design (stress-tests the Design contract)
    render_analytics.png   — same graph, node size bound to computed betweenness centrality
                              (the onya.viz.nx round trip -> draw_uli easter egg)
    render_degradation.png — a ~70-node generated graph: level-of-detail degradation, no hand pos
'''
import hashlib

import networkx as nx_lib

from onya.graph import graph
from onya.serial.literate import LiterateParser
from onya.terms import ONYA_INTERP
from onya.viz import nx as onx

from driver import draw, save

NB = 'https://example.org/books/things-fall-apart/'
PREFIXES = {'schema': 'https://schema.org/'}
# Hand-tuned anchors for the small reference graph — draw()'s pos= merges with spring layout for
# any node left unspecified, so this is purely cosmetic, not required.
POS = {NB + 'Okonkwo': (0.10, 0.05), NB + 'Unoka': (-0.85, 0.72),
       NB + 'Nwoye': (-0.55, -0.70), NB + 'Ezinma': (0.42, -0.78),
       NB + 'Umuofia': (0.95, 0.42)}


def _load_tfa():
    g = graph()
    with open('things_fall_apart.onya.md', encoding='utf-8') as f:
        LiterateParser().parse(f.read(), g)
    return g


def demo_two_designs():
    '''Same parsed graph, two visual languages, zero data-side changes.'''
    g = _load_tfa()

    fig = draw(g, 'uli_night', seed=2026, pos=POS, prefixes=PREFIXES,
               title='Things Fall Apart', subtitle='a family, woven — parsed & projected with Onya')
    save(fig, 'render_uli_night.png')
    print('  Generated: render_uli_night.png')

    fig = draw(g, 'aquatic', seed=7, pos=POS, prefixes=PREFIXES,
               title='Things Fall Apart', subtitle='the same graph, another visual language')
    save(fig, 'render_aquatic.png')
    print('  Generated: render_aquatic.png')


def demo_analytics_round_trip():
    '''The easter egg: project -> compute in networkx -> write_back -> draw with size_by=<metric>.

    Ties `onya.viz.nx`'s analytics round trip directly to the renderer: node size here reflects
    *computed betweenness centrality*, not raw degree, with zero bespoke plumbing in the driver.
    '''
    g = _load_tfa()
    mg = onx.to_networkx(g)
    centrality = nx_lib.betweenness_centrality(mg)
    metric = NB + 'betweenness'
    onx.write_back(g, metric, centrality, interp=ONYA_INTERP('number'))

    fig = draw(g, 'uli_night', seed=2026, pos=POS, prefixes=PREFIXES, size_by=metric,
               title='Things Fall Apart', subtitle='node size <- computed betweenness centrality')
    save(fig, 'render_analytics.png')
    print('  Generated: render_analytics.png (size_by betweenness centrality, via write_back)')


def demo_degradation():
    '''~70-node generated graph, spring layout, no hand positions: level-of-detail in action.'''
    ba = nx_lib.barabasi_albert_graph(70, 2, seed=5)
    lines = ['# @docheader', '', '* @document: https://example.org/demo/big',
              '* @nodebase: https://example.org/demo/big/', '* @schema: https://schema.org/', '']
    for n in ba.nodes:
        kind = 'Place' if n % 11 == 0 else 'Person'
        lines += [f'# N{n} [{kind}]', '', f'* name: Node {n}']
        lines += [f'* knows -> N{m}' for m in ba.neighbors(n) if m > n]
        lines += ['']
    g = graph()
    LiterateParser().parse('\n'.join(lines), g)

    fig = draw(g, 'uli_night', seed=11, prefixes=PREFIXES, title='Seventy nodes',
               subtitle='level-of-detail degradation, spring layout')
    save(fig, 'render_degradation.png')
    print('  Generated: render_degradation.png')


def demo_guards():
    '''The three "must never crash" cases from the prototype notes.'''
    # Empty graph (no non-document nodes): a clear, named ValueError — not a crash.
    empty = graph()
    LiterateParser().parse(
        '# @docheader\n\n* @document: https://example.org/demo/empty\n', empty)
    try:
        draw(empty, 'uli_night')
    except ValueError as e:
        print(f'  OK: empty graph raises ValueError: {e}')
    else:
        raise AssertionError('empty graph should have raised ValueError')

    # Single node, no schema:name: falls back to the compacted id as the label.
    single = graph()
    LiterateParser().parse('''\
# @docheader

* @document: https://example.org/demo/single
* @nodebase: https://example.org/demo/single/

# Solo [Thing]
''', single)
    fig = draw(single, 'uli_night', seed=1)
    save(fig, 'render_single_node.png')
    print('  OK: single node, no schema:name, renders (render_single_node.png)')


def demo_determinism():
    g = _load_tfa()
    digests = []
    for _ in range(2):
        fig = draw(g, 'uli_night', seed=2026, pos=POS, prefixes=PREFIXES, title='T', subtitle='S')
        save(fig, '_det.png')
        digests.append(hashlib.sha256(open('_det.png', 'rb').read()).hexdigest())
    assert digests[0] == digests[1], 'same seed should render byte-identical PNGs'

    fig2 = draw(g, 'uli_night', seed=99, pos=POS, prefixes=PREFIXES, title='T', subtitle='S')
    save(fig2, '_det.png')
    digest2 = hashlib.sha256(open('_det.png', 'rb').read()).hexdigest()
    assert digest2 != digests[0], 'a different seed should render different bytes'
    print('  OK: determinism (same seed -> identical bytes; different seed -> different)')


def main():
    print('Onya draw_uli renderer demo (issue #33)')
    print('=' * 50)
    demo_two_designs()
    demo_analytics_round_trip()
    demo_degradation()
    demo_guards()
    demo_determinism()
    print('=' * 50)
    print('All demos complete!')


if __name__ == '__main__':
    main()
