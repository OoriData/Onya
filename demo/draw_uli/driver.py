# SPDX-License-Identifier: Apache-2.0
'''
Design-agnostic drawing driver for the `draw_uli` demo — projection, data binding, layout, curve
geometry, level of detail.

Designs (see `uli_night.py`, `aquatic.py`) supply palette and motifs; the driver decides *what*
gets drawn where, and hands each design a fully-resolved view of every node and edge.

Status: this lives under `demo/`, not `pylib/` — it is a demo/prototype for a possible future
`onya.viz` (or `onya.draw`) renderer, not a supported library API. See Onya issue #33.

`include_document=False` (the default) drops the `onya:Document` node from the picture. This is
a deliberate opinion, not an oversight: a rendered graph is a picture of the *entities and
relationships an author described*, and the document node is bookkeeping about where that
description came from, not part of the subject matter. Pass `include_document=True` to draw it
anyway.
'''
import importlib
import warnings
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

SCHEMA = 'https://schema.org/'
NAME = SCHEMA + 'name'
DESCRIPTION = SCHEMA + 'description'

# Built-in designs, resolved by name without a real plugin/entry-point mechanism — this is a
# demo, not the library surface that would earn one. Module names are siblings of this file.
_BUILTIN_DESIGNS = {'uli_night': 'uli_night', 'aquatic': 'aquatic'}


def _networkx():
    try:
        import networkx
    except ImportError as e:  # pragma: no cover
        raise ImportError('draw_uli needs networkx: pip install "onya[nx]"') from e
    return networkx


def _pyplot():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise ImportError('draw_uli needs matplotlib: pip install matplotlib') from e
    return plt


def _resolve_design(design):
    '''Accept either a Design instance or the name of a built-in demo design.'''
    if isinstance(design, str):
        try:
            modname = _BUILTIN_DESIGNS[design]
        except KeyError:
            raise ValueError(f'Unknown design {design!r}; available: {sorted(_BUILTIN_DESIGNS)}') from None
        return importlib.import_module(modname).DESIGN
    return design


def _resolve_font(preferred: str) -> str:
    '''Fall back to a font matplotlib actually has, rather than silently mis-rendering glyphs.'''
    import matplotlib.font_manager as fm
    available = {f.name for f in fm.fontManager.ttflist}
    if preferred in available:
        return preferred
    fallback = 'DejaVu Sans'  # bundled with matplotlib; always present
    warnings.warn(f'font {preferred!r} not available; falling back to {fallback!r}', stacklevel=3)
    return fallback


@dataclass
class NodeView:
    '''Everything a design needs to render one node.'''
    id: str
    local: str            # display-compacted id
    types: tuple[str, ...]
    pos: np.ndarray
    radius: float
    degree: int
    size_value: float     # raw value driving radius (degree, or size_by property)
    label: str | None     # schema:name, or None when decluttered away
    caption: str | None   # schema:description, or None when decluttered away
    props: dict[str, list[Any]]
    detail: str           # 'full' | 'simple'

    def is_a(self, type_iri: str) -> bool:
        return type_iri in self.types


@dataclass
class EdgeView:
    '''Everything a design needs to render one edge. `points` is pre-trimmed to the node rims.'''
    src: NodeView
    tgt: NodeView
    label: str            # full label IRI
    local: str            # display-compacted label
    bow: float            # signed curvature; sign is the useful bit for ornament sides
    points: np.ndarray    # (N, 2) polyline along the curve, rims trimmed
    props: dict[str, list[Any]]
    show_label: bool


@dataclass
class Context:
    '''Shared render state. Designs read from this and may use its geometry helpers.'''
    fig: Any
    ax: Any
    rng: np.random.Generator
    nxgraph: Any
    nodes: dict[str, NodeView]
    edges: list[EdgeView]
    hub: NodeView | None
    bounds: tuple[float, float]      # (width, height) in data units
    palette: dict[str, str]
    font: str
    signature: bool

    # -- geometry helpers designs are encouraged to reuse ------------------------------------
    def chevron(self, points, *, color, lw=2.0, size=0.24, spread=0.13, alpha=0.9, zorder=2):
        '''Two-stroke arrowhead at the end of a polyline (which may be design-perturbed).'''
        if len(points) < 6:
            return
        tip, back = np.asarray(points[-1]), np.asarray(points[-6])
        t = tip - back
        n = np.linalg.norm(t)
        if n < 1e-9:
            return
        t = t / n
        perp = np.array([-t[1], t[0]])
        for s in (1, -1):
            w = tip - size * t + s * spread * perp
            self.ax.plot([w[0], tip[0]], [w[1], tip[1]], color=color, lw=lw, alpha=alpha,
                         zorder=zorder, solid_capstyle='round')

    def curve_label(self, points, text, *, side=1, color='white', fontsize=10.5, offset=0.24,
                    alpha=0.75, zorder=5, style='italic'):
        '''Label riding along a polyline, rotated to the local tangent.'''
        pts = np.asarray(points)
        if len(pts) < 3:
            return
        i = len(pts) // 2
        p, q = pts[i], pts[min(i + 1, len(pts) - 1)]
        d = q - p
        ang = np.degrees(np.arctan2(d[1], d[0]))
        if ang > 90:
            ang -= 180
        if ang < -90:
            ang += 180
        perp = np.array([-d[1], d[0]])
        n = np.linalg.norm(perp)
        off = perp / n * offset * side if n > 1e-9 else np.zeros(2)
        self.ax.text(*(p + off), text, color=color, alpha=alpha, fontsize=fontsize, style=style,
                     ha='center', va='center', rotation=ang, fontfamily=self.font, zorder=zorder)

    def wobble(self, points, *, amplitude=0.12, cycles=2.5, phase=None):
        '''Perturb a polyline sinusoidally along its normal — kelp, cables, hand-drawn lines.'''
        pts = np.asarray(points, dtype=float)
        if len(pts) < 3:
            return pts
        phase = self.rng.uniform(0, 2 * np.pi) if phase is None else phase
        t = np.linspace(0, 1, len(pts))
        d = np.gradient(pts, axis=0)
        norms = np.stack([-d[:, 1], d[:, 0]], axis=1)
        mag = np.linalg.norm(norms, axis=1, keepdims=True)
        norms = np.divide(norms, mag, out=np.zeros_like(norms), where=mag > 1e-9)
        taper = np.sin(np.pi * t)[:, None]          # pinned at both ends
        return pts + norms * taper * amplitude * np.sin(2 * np.pi * cycles * t + phase)[:, None]

    def gradient_fill(self, low_color, high_color, *, zorder=0, alpha=0.95):
        '''Vertical two-stop gradient background, safe under `ax.set_aspect('equal')` (pins
        `aspect='auto'` on the underlying `imshow`, which fights the equal-aspect axes otherwise).'''
        from matplotlib.colors import LinearSegmentedColormap
        W, H = self.bounds
        grad = np.linspace(0, 1, 256).reshape(-1, 1)
        cmap = LinearSegmentedColormap.from_list('gradient_fill', [low_color, high_color])
        self.ax.imshow(grad, extent=(0, W, 0, H), origin='lower', aspect='auto', zorder=zorder,
                       cmap=cmap, alpha=alpha)


@runtime_checkable
class Design(Protocol):
    '''A pluggable visual language. Every hook is optional except node and edge.'''
    name: str
    palette: dict[str, str]
    background_color: str
    font: str

    def node(self, ctx: Context, nv: NodeView) -> None: ...
    def edge(self, ctx: Context, ev: EdgeView) -> None: ...


# ---- data binding ---------------------------------------------------------------------------

def _local_name(iri: str, prefixes: dict[str, str] | None) -> str:
    if prefixes:
        from onya.util import compact_iri
        try:
            return compact_iri(iri, prefixes)
        except Exception:  # noqa: BLE001 — display path must never break a render
            pass
    return iri.rstrip('/').rsplit('/', 1)[-1].rsplit('#', 1)[-1] or iri


def _size_values(mg, size_by):
    '''Degree by default. Otherwise the projection was made with `apply_interps=True`, so the
    property already arrived as a Python value via `onya.interp.value_of` (e.g. `@as: number` ->
    int/Decimal) — this just takes the first value and float-casts it, degrading non-numeric or
    missing values to 0.0 rather than raising.'''
    if size_by is None:
        return {n: float(d) for n, d in mg.degree()}, 'degree'
    out = {}
    for n, data in mg.nodes(data=True):
        vals = data.get(size_by) or []
        try:
            out[n] = float(vals[0]) if vals else 0.0
        except (TypeError, ValueError):
            out[n] = 0.0
    return out, size_by


def draw(g, design, *, seed=None, pos=None, size_by=None, figsize=(16, 10), prefixes=None,
         include_document=False, title=None, subtitle=None, label_top_k=None, signature=True):
    '''Render an Onya graph through a Design. Returns a matplotlib Figure.

    `design`: a Design instance, or the name of a built-in demo design ('uli_night', 'aquatic').
    `size_by`: None (default) sizes nodes by degree; otherwise a property IRI, read through
    `onya.interp.value_of` (non-numeric/missing values degrade to 0.0, never raise).
    `include_document`: see module docstring — defaults to False, a deliberate opinion.
    Raises ValueError if the graph has nothing to draw (no non-document nodes).
    '''
    networkx = _networkx()
    plt = _pyplot()
    design = _resolve_design(design)
    from onya.viz import nx as onx
    from onya.terms import ONYA_DOCUMENT

    mg = onx.to_networkx(g, apply_interps=size_by is not None)
    if not include_document:
        drop = [n for n, d in mg.nodes(data=True) if str(ONYA_DOCUMENT) in d.get('types', ())]
        mg.remove_nodes_from(drop)
    if mg.number_of_nodes() == 0:
        raise ValueError('nothing to draw: graph has no non-document nodes')

    rng = np.random.default_rng(seed)
    sizes, _channel = _size_values(mg, size_by)
    smax = max(sizes.values()) or 1.0

    # layout: explicit override wins; else spring, seeded for reproducibility
    if pos is None:
        raw = networkx.spring_layout(mg, seed=seed if seed is not None else 0, k=0.9)
    else:
        raw = {n: np.asarray(p, dtype=float) for n, p in pos.items()}
        missing = [n for n in mg.nodes if n not in raw]
        if missing:
            fill = networkx.spring_layout(mg.subgraph(missing), seed=seed or 0)
            raw.update(fill)

    W, H = figsize
    P = np.array([raw[n] for n in mg.nodes], dtype=float)
    lo, hi = P.min(axis=0), P.max(axis=0)
    degenerate = hi - lo < 1e-9    # a lone node, or a cluster spring_layout collapsed to one point
    span = np.where(degenerate, 1.0, hi - lo)
    margin = 0.14
    scaled = {}
    for n in mg.nodes:
        u = (np.asarray(raw[n], dtype=float) - lo) / span
        u = np.where(degenerate, 0.5, u)      # center rather than pin to a corner
        scaled[n] = np.array([margin * W + u[0] * W * (1 - 2 * margin),
                              margin * H + u[1] * H * (1 - 2 * margin)])

    # radii: shrink the band as the graph grows, so big graphs stay atmospheric
    n_nodes = mg.number_of_nodes()
    r_max = float(np.clip(2.2 / np.sqrt(n_nodes), 0.16, 1.15))
    r_min = r_max * 0.5
    radii = {n: r_min + (r_max - r_min) * (sizes[n] / smax) for n in mg.nodes}

    # level of detail
    top_k = label_top_k if label_top_k is not None else (n_nodes if n_nodes <= 24 else 12)
    ranked = sorted(mg.nodes, key=lambda n: sizes[n], reverse=True)
    labelled = set(ranked[:top_k])
    captioned = set(ranked[:top_k]) if n_nodes <= 8 else set()

    nodes = {}
    for n, data in mg.nodes(data=True):
        props = {k: v for k, v in data.items() if k not in ('types',)}
        name = (data.get(NAME) or [None])[0]
        desc = (data.get(DESCRIPTION) or [None])[0]
        nodes[n] = NodeView(
            id=n, local=_local_name(n, prefixes), types=tuple(data.get('types', ())),
            pos=scaled[n], radius=radii[n], degree=mg.degree(n), size_value=sizes[n],
            label=(name or _local_name(n, prefixes)) if n in labelled else None,
            caption=desc if n in captioned else None,
            props=props, detail='full' if radii[n] >= 0.34 else 'simple')

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(design.background_color)
    ax.set_facecolor(design.background_color)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect('equal')
    ax.axis('off')

    ctx = Context(fig=fig, ax=ax, rng=rng, nxgraph=mg, nodes=nodes, edges=[],
                  hub=nodes[ranked[0]], bounds=(W, H), palette=design.palette,
                  font=_resolve_font(design.font), signature=signature)

    # edges: fan parallel pairs automatically, trim to rims
    fan_count: dict[tuple[str, str], int] = {}
    for u, v, _k in mg.edges(keys=True):
        key = tuple(sorted((u, v)))
        fan_count[key] = fan_count.get(key, 0) + 1
    fan_seen: dict[tuple[str, str], int] = {}
    for u, v, _k, data in mg.edges(keys=True, data=True):
        key = tuple(sorted((u, v)))
        total = fan_count[key]
        i = fan_seen.get(key, 0)
        fan_seen[key] = i + 1
        if total == 1:
            bow = 0.18
        else:  # spread the fan symmetrically about the straight line
            bow = 0.34 * ((i - (total - 1) / 2) / max(total - 1, 1) * 2)
            bow = bow if abs(bow) > 1e-6 else 0.06
        pts = _qbezier(nodes[u].pos, nodes[v].pos, bow)
        keep = [(np.linalg.norm(p - nodes[u].pos) > nodes[u].radius * 1.32) and
                (np.linalg.norm(p - nodes[v].pos) > nodes[v].radius * 1.42) for p in pts]
        pts = pts[keep]
        if len(pts) < 4:
            continue
        label = data.get('label', '')
        ctx.edges.append(EdgeView(
            src=nodes[u], tgt=nodes[v], label=label, local=_local_name(label, prefixes),
            bow=bow, points=pts,
            props={k: v for k, v in data.items() if k != 'label'},
            show_label=n_nodes <= 24))

    if hasattr(design, 'background'):
        design.background(ctx)
    for ev in ctx.edges:
        design.edge(ctx, ev)
    for nv in nodes.values():
        design.node(ctx, nv)
    if hasattr(design, 'chrome'):
        design.chrome(ctx, title, subtitle)

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig


def _qbezier(p0, p1, bow=0.18, n=80):
    p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    mid = (p0 + p1) / 2
    d = p1 - p0
    norm = np.linalg.norm(d)
    perp = np.array([-d[1], d[0]]) / (norm + 1e-9)
    ctrl = mid + bow * norm * perp
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * ctrl + t ** 2 * p1


def save(fig, path, *, facecolor=None):
    fig.savefig(path, facecolor=facecolor or fig.get_facecolor())
    return path
