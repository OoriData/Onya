#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# demo/nx_analytics/nx_demo.py

'''
Demo: project an Onya graph into networkx, run analytics, and write the results back as
first-class Onya assertions.

Usage (from a fresh install with the extra):
    pip install -e '.[nx]'      # or: uv pip install -U '.[nx]'
    python nx_demo.py

The round trip is the point: analytics computed in networkx come home as typed, merge-safe
Onya properties, queryable with graph.select and serializable back to Onya Literate.

Optional: `pip install matplotlib` to also render a community-colored layout to social.png.
'''

import sys
from io import StringIO
from pathlib import Path

import networkx

from onya.graph import graph
from onya.serial import nx
from onya.serial.literate import LiterateParser, write
from onya.terms import ONYA_INTERP
from onya.interp import value_of

HERE = Path(__file__).parent
ANALYTICS = 'https://oori.dev/onya/demo/analytics/'
BETWEENNESS = ANALYTICS + 'betweenness'
COMMUNITY = ANALYTICS + 'community'


def main():
    # 1. Parse the small social graph.
    g = graph()
    LiterateParser().parse((HERE / 'social.onya').read_text(), g)

    # 2. Project into networkx (a MultiDiGraph), then narrow to the people — the document node
    #    that `@document` mints is a real node but not a social actor. Onya's type query picks
    #    the subgraph of interest; networkx does the rest.
    full = nx.to_networkx(g)
    people = {str(n.id) for n in g.typematch('https://schema.org/Person')}
    mg = full.subgraph(people).copy()
    print(f'Projected {full.number_of_nodes()} nodes; analyzing {mg.number_of_nodes()} people, '
          f'{mg.number_of_edges()} edges.\n')

    # 3. Compute analytics with networkx's own API — no Onya wrappers.
    betweenness = networkx.betweenness_centrality(mg)
    # Louvain communities run on the undirected view; seed for a deterministic demo.
    communities = networkx.community.louvain_communities(mg.to_undirected(), seed=42)
    community_of = {node: idx for idx, members in enumerate(communities) for node in members}

    print('Betweenness centrality:')
    for node, score in sorted(betweenness.items(), key=lambda kv: kv[1], reverse=True):
        print(f'  {node.rsplit("/", 1)[-1]:6} {score:.3f}  community {community_of[node]}')

    # 4. Write both back into the Onya graph. Centrality carries the `number` contract so it
    #    round-trips as a real number; community index is written as a plain string.
    # Round the raw floats before storing — the `number` contract is exact, so it would
    # otherwise faithfully preserve binary artifacts like 0.30000000000000004.
    betweenness = {node: round(score, 4) for node, score in betweenness.items()}
    n1 = nx.write_back(g, BETWEENNESS, betweenness, interp=ONYA_INTERP('number'))
    n2 = nx.write_back(g, COMMUNITY, community_of)
    print(f'\nWrote {n1} betweenness + {n2} community properties back into the graph.')

    # 5. The results are ordinary Onya assertions now — query them back through select().
    print('\nTop bridge (highest betweenness), read back via graph.select + value_of:')
    ranked = sorted(g.select(label=BETWEENNESS), key=value_of, reverse=True)
    top = ranked[0]
    print(f'  {top.origin.id}  ->  {value_of(top)} ({type(value_of(top)).__name__})')

    # 6. Serialize the annotated graph back to Onya Literate.
    out = StringIO()
    write(g, out=out, document='https://oori.dev/onya/demo/social',
          nodebase='https://oori.dev/onya/demo/social/', schema='https://schema.org/',
          prefixes={'an': ANALYTICS})
    print('\n--- Annotated Onya Literate ---\n')
    print(out.getvalue())

    _maybe_render(mg, community_of)


def _maybe_render(mg, community_of):
    '''Render a community-colored spring layout, if matplotlib is available.'''
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print('(pip install matplotlib to also render social.png)')
        return
    undirected = mg.to_undirected()
    colors = [community_of[n] for n in undirected.nodes]
    labels = {n: n.rsplit('/', 1)[-1] for n in undirected.nodes}
    pos = networkx.spring_layout(undirected, seed=42)
    networkx.draw(undirected, pos, labels=labels, node_color=colors, cmap='Set2',
                  node_size=1200, font_size=9)
    out_png = HERE / 'social.png'
    plt.savefig(out_png, dpi=120, bbox_inches='tight')
    print(f'(rendered {out_png})')


if __name__ == '__main__':
    sys.exit(main())
