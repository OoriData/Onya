**Onya `draw_uli` Renderer Demo**

A theme-able, code-driven graph illustration renderer — the graph as art, not a diagram. Built on
`onya.viz.nx` (projection) + matplotlib. See [issue #33](https://github.com/OoriData/Onya/issues/33).

**Status: prototype, demo-only.** This does *not* live under `pylib/` — it is not a supported
library API (no extras entry, no CLI subcommand, no plugin discovery). The bar for promoting it
into `onya.viz` is specifically an **edge-side degradation strategy**: `render_degradation.png`
(below) shows the honest current gap — node motifs degrade gracefully at 70 nodes, but the edges
don't, and the result is a hairball rather than an illustration. Until that's solved, "looks
great at 5 nodes" and "scales to real-world graphs" are different claims.

# Running the demo

```bash
pip install "onya[nx]" matplotlib   # not a project dependency; ad hoc for this demo, like nx_analytics
cd demo/draw_uli
python render_demo.py
```

Generates (gitignored, per `demo/.gitignore` — rerun to reproduce):

- **render_uli_night.png** — a small family graph ("Things Fall Apart"), the `uli_night` design:
  the graph as a spider's orb web on an indigo night, in a palette borrowed from uli
  body-and-wall painting.
- **render_aquatic.png** — the *same* parsed graph, the `aquatic` design: nodes as anemones and
  coral heads, edges as swaying kelp. Written as a stress test of the design contract (gradient
  background, self-perturbed edge geometry) — proof that a second, visually unrelated design
  needs zero driver changes.
- **render_analytics.png** — the same graph again, but node size is bound to *computed
  betweenness centrality* (`onya.viz.nx.write_back` → `size_by=<metric IRI>`) instead of raw
  degree. This is the point of the `onya.viz.nx` round trip: analytics computed in networkx come
  back as first-class, typed Onya properties, and the renderer can bind to them like any other
  data.
- **render_degradation.png** — a generated ~70-node graph, no hand-tuned positions: shows the
  level-of-detail mechanism (shrinking radius band, top-k labels, caption suppression, simplified
  motifs below a radius threshold) — and its current limit (see Status above).
- **render_single_node.png** — a one-node graph with no `schema:name`: falls back to the
  compacted node id as its label, centered rather than pinned to a layout corner.

The script also exercises (and asserts) the "must never crash" guard cases from the design notes
(empty graph, single node, missing `schema:name`) and a determinism check (same `seed` →
byte-identical PNG; a different `seed` → different bytes).

# Layout

- `driver.py` — design-agnostic: projection (via `onya.viz.nx`), data binding (degree/property →
  size, type → motif dispatch, `schema:name`/`schema:description` → text, edge label → ornament),
  layout (spring, with an optional `pos=` override that merges rather than replaces), curve
  geometry (bezier + rim-trimming + parallel-edge fanning), and level-of-detail thresholds.
- `uli_night.py`, `aquatic.py` — the pluggable `Design`s: palette, motifs, atmosphere, chrome.
  Only `node` and `edge` are required hooks; `background` and `chrome` are optional.
- `things_fall_apart.onya.md` — the small reference graph (Onya Literate).
- `render_demo.py` — produces everything above.

# A deliberate opinion worth knowing about

`draw(g, ...)` defaults to `include_document=False`: the `onya:Document` node (bookkeeping about
where the graph came from) is dropped from the picture. A rendered graph is meant to show the
entities and relationships an author described, not the metadata about that description. Pass
`include_document=True` to draw it anyway.

# Design contract, in brief

```python
class Design(Protocol):
    name: str
    palette: dict[str, str]
    background_color: str
    font: str
    def node(self, ctx, nv): ...      # required
    def edge(self, ctx, ev): ...      # required
    def background(self, ctx): ...    # optional
    def chrome(self, ctx, title, subtitle): ...  # optional
```

`ctx` carries the figure/axes, a seeded `rng` (never use global random state — renders must be
reproducible), palette, bounds, the projected graph, and the highest-degree "hub" node, plus
geometry helpers every design is encouraged to reuse: `chevron`, `curve_label`, `wobble` (for
kelp/cables/hand-drawn perturbation), and `gradient_fill` (an aspect-safe gradient background).
Edge geometry is handed to designs as `ev.points` (already trimmed to the node rims) so a design
can transform it (e.g. `aquatic`'s kelp sway) before drawing.
