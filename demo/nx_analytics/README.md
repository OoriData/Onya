**Onya networkx Analytics Demo**

This directory shows the `onya.serial.nx` round trip: **project** an Onya graph into
[networkx](https://networkx.org/), **compute** graph analytics with networkx's own API, and
**write the results back** into the Onya graph as typed, merge-safe assertions.

# Running the demo

From the repository root, install Onya with the `nx` extra, then run the script:

```bash
uv pip install -U '.[nx]'      # or: pip install -e '.[nx]'
cd demo/nx_analytics
python nx_demo.py
```

The script:

1. Parses `social.onya` — two friendship triangles bridged by a single `knows` edge.
2. Projects it with `to_networkx` (a `networkx.MultiDiGraph`), then narrows to the
   `schema:Person` nodes with `graph.typematch` (the `@document` node is a real node, not a
   social actor).
3. Computes **betweenness centrality** and **Louvain communities** with networkx.
4. Writes both back with `write_back` — centrality carrying the `number` interpretation
   (`ONYA_INTERP('number')`), community index as a plain string.
5. Reads the top bridge back with `graph.select` + `onya.interp.value_of` (a real `Decimal`).
6. Serializes the annotated graph to Onya Literate with `write`.

Optional: `pip install matplotlib` to also render a community-colored layout to `social.png`.
matplotlib is **not** a dependency of Onya — the script degrades gracefully without it.

# Using in your code

```python
import networkx
from onya.graph import graph
from onya.serial import nx
from onya.serial.literate import read
from onya.terms import ONYA_INTERP

g = read('social.onya')
mg = nx.to_networkx(g)                                   # -> networkx.MultiDiGraph
scores = networkx.betweenness_centrality(mg)
nx.write_back(g, 'https://example.org/betweenness', scores, interp=ONYA_INTERP('number'))
# scores are now first-class Onya assertions: queryable via g.select, and merge-safe on store.put
```

Notes:

- The projection is **lossy by design** (v1): first-level structure only. Edges to identified
  assertions are skipped (with a warning); nested assertions below the first level are dropped.
  See the `onya.serial.nx` module docstring for the full loss policy.
- The projection reflects the graph **as it is**. Parallel same-skeleton edges stay distinct;
  call `g.merge()` first if you want a normalized projection.
