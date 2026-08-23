# SPDX-License-Identifier: Apache-2.0
'''
flatirons — the graph as the view west from downtown Boulder: an alpenglow sky over a silhouette
row of the Flatirons and their foothill pines, in a graphic vocabulary borrowed from Colorado
itself (Fountain Formation sandstone, aspen gold, the state's columbine, CU Boulder's buff and
black). Places render as miniature tilted slabs, people as trailside cairns, everything else
(organizations and their subclasses, events, ...) as a trailhead signpost. Edges are a dashed
trail with painted blazes.

Everything here is data-driven off the graph the driver hands it: degree -> size, Place/Person ->
motif, name/description -> text, edge label -> blaze. Swap in a different Onya Literate file and
re-hike with zero code edits.
'''
import numpy as np
from matplotlib.patches import Circle, Ellipse, Polygon, Rectangle

SCHEMA = 'https://schema.org/'
PLACE = SCHEMA + 'Place'
PERSON = SCHEMA + 'Person'


class Flatirons:
    name = 'flatirons'
    background_color = '#16233c'
    font = 'DejaVu Sans'
    signature = 'ọ́nyà ugwu — a web of the foothills'
    palette = {
        'sky': '#16233c',          # high-altitude indigo, above the front-range haze
        'horizon': '#e8935a',      # alpenglow low on the skyline
        'glow': '#f6cf8e',
        'rock': '#a35a42',         # Fountain Formation sandstone -- the Flatirons themselves
        'rock_shadow': '#6e3a2c',
        'pine': '#33503f',
        'pine_dark': '#20362a',
        'aspen': '#d9a92a',
        'buff': '#cfb87c',         # CU Boulder buff
        'black': '#18120c',        # CU Boulder black
        'columbine': '#6a72ad',    # Colorado's state flower
        'snow': '#f4efe4',
    }

    # -- the view west ----------------------------------------------------------------------
    def background(self, ctx):
        ax, rng, p = ctx.ax, ctx.rng, self.palette
        W, H = ctx.bounds

        ctx.gradient_fill(p['horizon'], p['sky'])

        stars = rng.uniform([0, H * 0.55], [W, H], size=(70, 2))
        ax.scatter(stars[:, 0], stars[:, 1], s=rng.uniform(0.3, 2.0, 70), c=p['snow'],
                   alpha=0.35, zorder=0, linewidths=0)

        sun = np.array([W * 0.86, H * 0.80])
        for rr, aa in ((0.9, 0.05), (0.6, 0.09), (0.34, 0.5)):
            ax.add_patch(Circle(sun, rr, color=p['glow'], alpha=aa, zorder=0))

        # the Flatirons themselves: five tilted slabs on the western skyline
        base_y = H * 0.30
        slabs = [(0.16, 0.62, -0.18), (0.27, 0.86, -0.15), (0.37, 1.05, -0.12),
                 (0.47, 0.92, -0.16), (0.57, 0.68, -0.20)]
        for i, (cx, height, lean) in enumerate(slabs):
            x = cx * W
            width = W * 0.09
            top = np.array([x + lean * height, base_y + height * H * 0.32])
            poly = np.array([[x - width / 2, base_y], [x + width / 2, base_y],
                             top + [width * 0.28, 0], top - [width * 0.28, 0]])
            face = p['rock'] if i % 2 == 0 else p['rock_shadow']
            ax.add_patch(Polygon(poly, closed=True, color=face, alpha=0.92, zorder=1, lw=0))
            for t in (0.32, 0.58, 0.8):
                a = poly[0] * (1 - t) + poly[3] * t
                b = poly[1] * (1 - t) + poly[2] * t
                ax.plot([a[0], b[0]], [a[1], b[1]], color=p['rock_shadow'], lw=0.8, alpha=0.35,
                        zorder=1)

        # foothill pines, closer and darker, along the very base
        px = np.sort(rng.uniform(0, W, int(W * 3)))
        for x in px:
            h = rng.uniform(0.18, 0.42)
            w = h * 0.55
            y0 = base_y * rng.uniform(0.0, 0.55)
            tri = np.array([[x - w / 2, y0], [x + w / 2, y0], [x, y0 + h]])
            ax.add_patch(Polygon(tri, closed=True, color=p['pine_dark'], alpha=0.85, zorder=1,
                                 lw=0))

        # a hawk or two riding the thermals above the ridge
        for _ in range(3):
            cx, cy = rng.uniform(W * 0.1, W * 0.9), rng.uniform(H * 0.62, H * 0.92)
            s = rng.uniform(0.06, 0.11)
            wing = np.array([[cx - s, cy], [cx, cy + s * 0.4], [cx + s, cy]])
            ax.plot(wing[:, 0], wing[:, 1], color=p['black'], lw=1.1, alpha=0.5, zorder=1)

    # -- motifs -------------------------------------------------------------------------------
    def node(self, ctx, nv):
        ax, p, r, c = ctx.ax, self.palette, nv.radius, nv.pos
        ax.add_patch(Circle(c, r * 1.3, color=p['sky'], alpha=0.88, zorder=3))  # clear the skyline

        if nv.detail == 'simple':
            ring = p['rock'] if nv.is_a(PLACE) else (p['aspen'] if nv.is_a(PERSON) else p['buff'])
            ax.add_patch(Circle(c, r, fc='none', ec=ring, lw=2.0, alpha=0.95, zorder=4))
            ax.add_patch(Circle(c, r * 0.32, color=ring, zorder=4))
        elif nv.is_a(PLACE):
            self._slab(ax, c, r, p)
        elif nv.is_a(PERSON):
            self._cairn(ax, c, r, nv.degree, p)
        else:
            self._waymarker(ax, c, r, nv.degree, p)

        if nv.label:
            ax.text(c[0], c[1] - r - 0.34, nv.label, color=p['snow'],
                    fontsize=float(np.clip(11 + 6 * r, 10, 18)), ha='center', va='top',
                    fontfamily=ctx.font, zorder=5)
        if nv.caption:
            ax.text(c[0], c[1] - r - 0.78, nv.caption, color=p['snow'], alpha=0.6, fontsize=9.5,
                    style='italic', ha='center', va='top', fontfamily=ctx.font, zorder=5)

    @staticmethod
    def _slab(ax, c, r, p):
        '''A single Flatiron in miniature: a tilted rock slab with strata and pines at its foot.'''
        cx, cy = c
        top = np.array([cx - r * 0.35, cy + r * 1.05])
        poly = np.array([[cx - r * 0.85, cy - r * 0.7], [cx + r * 0.85, cy - r * 0.7],
                         top + [r * 0.35, 0], top - [r * 0.35, 0]])
        ax.add_patch(Polygon(poly, closed=True, facecolor=p['rock'], edgecolor=p['buff'], lw=1.4,
                             alpha=0.95, zorder=4))
        for t in (0.3, 0.55, 0.78):
            a = poly[0] * (1 - t) + poly[3] * t
            b = poly[1] * (1 - t) + poly[2] * t
            ax.plot([a[0], b[0]], [a[1], b[1]], color=p['rock_shadow'], lw=1.2, alpha=0.6, zorder=5)
        for dx in (-0.5, 0.0, 0.5):
            base = np.array([cx + dx * r * 0.7, cy - r * 0.72])
            ax.add_patch(Polygon(np.array([[base[0] - r * 0.14, base[1]],
                                           [base[0] + r * 0.14, base[1]],
                                           [base[0], base[1] + r * 0.34]]),
                                 closed=True, color=p['pine'], alpha=0.9, zorder=5))

    @staticmethod
    def _cairn(ax, c, r, degree, p):
        '''A person as a trail cairn: hand-stacked stones, Colorado's own wayfinding marker --
        taller and more established (more stones) the more the graph connects through them, with
        columbine growing wild at its foot.'''
        cx, cy = c
        rng_local = np.array([0.5, -0.5, 0.35, -0.35, 0.15])   # fixed hand-stacked wobble, no rng
        nstones = int(np.clip(3 + degree // 2, 3, 6))
        stones = [p['rock'], p['rock_shadow'], p['rock'], p['buff'], p['rock_shadow'], p['rock']]
        base = cy - r * 0.85
        y = base
        for i in range(nstones):
            frac = 1 - i / max(nstones, 1) * 0.5
            w, h = r * 1.15 * frac, r * (0.46 - i * 0.035)
            dx = rng_local[i % len(rng_local)] * r * 0.16
            ax.add_patch(Ellipse((cx + dx, y + h / 2), w, h, facecolor=stones[i % len(stones)],
                                 edgecolor=p['black'], lw=0.8, alpha=0.95, zorder=4 + i))
            y += h * 0.62
        for a, d in ((-0.9, 0.62), (1.1, 0.7), (2.6, 0.58)):    # columbine at the foot
            q = np.array([cx + d * r * np.cos(a), base - r * 0.12 + d * r * 0.22 * np.sin(a)])
            for pa in np.linspace(0, 2 * np.pi, 5, endpoint=False):
                ax.add_patch(Circle(q + r * 0.09 * np.array([np.cos(pa), np.sin(pa)]), r * 0.055,
                                    color=p['columbine'], alpha=0.9, zorder=4))
            ax.add_patch(Circle(q, r * 0.045, color=p['aspen'], zorder=5))
        cap = np.array([cx, y + r * 0.05])                     # a small summit flag on top
        ax.plot([cap[0], cap[0]], [cap[1], cap[1] + r * 0.34], color=p['pine_dark'], lw=1.3,
                zorder=6 + nstones)
        ax.add_patch(Polygon(np.array([cap + [0, r * 0.34], cap + [r * 0.26, r * 0.25],
                                       cap + [0, r * 0.17]]), closed=True, color=p['aspen'],
                             alpha=0.95, zorder=6 + nstones))

    @staticmethod
    def _waymarker(ax, c, r, degree, p):
        '''Organizations, institutions, and events as a trailhead signpost: the routed-wood,
        peak-capped placards that line every Boulder OSMP trail, in CU's own buff and black.'''
        cx, cy = c
        post_w = r * 0.15
        ax.add_patch(Rectangle((cx - post_w / 2, cy - r * 0.95), post_w, r * 1.15,
                               color=p['pine_dark'], zorder=4))
        ax.add_patch(Circle((cx, cy - r * 0.95), r * 0.09, color=p['rock_shadow'], zorder=4))
        board_w, board_h = r * 1.7, r * 0.85
        board_y = cy + r * 0.05
        ax.add_patch(Rectangle((cx - board_w / 2, board_y), board_w, board_h, facecolor=p['black'],
                               edgecolor=p['buff'], lw=1.6, alpha=0.95, zorder=5))
        cap = np.array([[cx - board_w / 2 - r * 0.1, board_y + board_h],
                        [cx + board_w / 2 + r * 0.1, board_y + board_h],
                        [cx, board_y + board_h + r * 0.3]])
        ax.add_patch(Polygon(cap, closed=True, color=p['rock_shadow'], alpha=0.95, zorder=5))
        nlines = int(np.clip(2 + degree // 3, 2, 4))            # routed lettering, more the busier
        for i in range(nlines):
            ly = board_y + board_h * (0.72 - i * 0.22)
            width = board_w * (0.64 if i == 0 else 0.42)
            ax.plot([cx - width / 2, cx + width / 2], [ly, ly], color=p['buff'],
                    lw=2.2 if i == 0 else 1.4, alpha=0.9, zorder=6)

    # -- trail ----------------------------------------------------------------------------------
    def edge(self, ctx, ev):
        ax, p = ctx.ax, self.palette
        pts = ctx.wobble(ev.points, amplitude=0.05, cycles=1.4)   # a switchbacking trail, not a wire
        ax.plot(pts[:, 0], pts[:, 1], color=p['snow'], lw=1.6, alpha=0.55, zorder=2,
                linestyle=(0, (5, 3)), solid_capstyle='round')
        side = float(np.sign(ev.bow)) or 1.0
        for q, s in zip(pts[6:-8:11], pts[7:-7:11]):        # painted trail blazes
            t = (s - q) / (np.linalg.norm(s - q) + 1e-9)
            n = np.array([-t[1], t[0]])
            q = q + n * 0.12 * side
            ax.add_patch(Rectangle(q - [0.045, 0.07], 0.09, 0.14, color=p['buff'], alpha=0.9,
                                   zorder=2, lw=0))
        ctx.chevron(pts, color=p['snow'])
        if ev.show_label:
            ctx.curve_label(pts, ev.local, side=side, color=p['glow'])

    # -- chrome -----------------------------------------------------------------------------
    def chrome(self, ctx, title, subtitle):
        ax, p = ctx.ax, self.palette
        W, H = ctx.bounds
        if title:
            ax.text(0.55, H - 0.55, title, color=p['snow'], fontsize=27, fontfamily=ctx.font,
                    va='top', zorder=6)
        if subtitle:
            ax.text(0.57, H - 1.18, subtitle, color=p['glow'], fontsize=12.5, style='italic',
                    fontfamily=ctx.font, va='top', zorder=6)
        if ctx.signature:
            ax.text(W - 0.4, 0.42, ctx.signature, color=p['snow'], alpha=0.7,
                    fontsize=12, style='italic', ha='right', fontfamily=ctx.font, zorder=6)


DESIGN = Flatirons()
