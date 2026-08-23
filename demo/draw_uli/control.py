# SPDX-License-Identifier: Apache-2.0
'''
control — the optional, small TOML sidecar for draw_uli renders: presentation-only hints that
have no natural home in an Onya graph itself, chiefly hand-tuned node position anchors. This is
a deliberate split from `driver._docheader_text`: title/subtitle/signature are *about the graph's
subject matter* and belong in its `@docheader`; where a node happens to sit on the canvas is
purely a rendering choice, so it lives here instead, in a file the graph knows nothing about.

Shape (all keys optional):

    seed = 2026
    figsize = [16, 10]
    label_top_k = 24
    size_by = "https://example.org/vocab/betweenness"

    [pos]
    Okonkwo = [0.10, 0.05]     # bare node ids, as written in the .onya file's `# NodeID` headers
    Umuofia = [0.95, 0.42]     # resolved against @nodebase by `expand_pos`; an absolute IRI
                               # (containing "://") is used as-is instead

Read by both `render_demo.py` and `onya_draw.py`.
'''
import tomllib


def load(path):
    '''Parse a control TOML file into a plain dict. `{}` if `path` is None.'''
    if path is None:
        return {}
    with open(path, 'rb') as f:
        return tomllib.load(f)


def expand_pos(control, nodebase):
    '''Resolve a control file's `[pos]` table to full node-id -> (x, y) pairs, the shape
    `driver.draw(pos=...)` expects. None if the control file has no `[pos]` table (draw() then
    falls back entirely to its own spring layout).'''
    raw = control.get('pos')
    if not raw:
        return None
    return {(local if '://' in local else (nodebase or '') + local): tuple(xy)
            for local, xy in raw.items()}
