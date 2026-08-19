# SPDX-License-Identifier: Apache-2.0
'''
aquatic — the same graph as a reef: nodes as anemones and coral heads, edges as kelp strands
swaying in the current, sunlight falling in caustic shafts through the water column.

Written as a deliberate stress test of the Design contract: unlike uli_night it needs a gradient
background, per-node radiating strokes rather than concentric circles, and edge geometry it
perturbs itself (via ctx.wobble) before asking the driver for arrowheads and labels.
'''
import numpy as np
from matplotlib.patches import Circle, Ellipse, Polygon

SCHEMA = 'https://schema.org/'
PLACE = SCHEMA + 'Place'


class Aquatic:
    name = 'aquatic'
    background_color = '#04212f'
    font = 'DejaVu Sans'
    signature = 'ọ́nyà mmiri — a web in water'
    palette = {
        'deep': '#04212f',
        'shallow': '#0d5a6b',
        'caustic': '#8fe3d8',
        'foam': '#e8f7f4',
        'kelp': '#4f8f5f',
        'kelp_light': '#8bc079',
        'coral': '#e5705a',
        'coral_deep': '#a83f4a',
        'anemone': '#d98cc0',
        'sand': '#d9c9a3',
    }

    # -- water column ---------------------------------------------------------------------
    def background(self, ctx):
        ax, rng, p = ctx.ax, ctx.rng, self.palette
        W, H = ctx.bounds

        ctx.gradient_fill(p['deep'], p['shallow'])   # depth gradient: light above, dark below

        # caustic shafts slanting down from the surface
        for _ in range(9):
            x0 = rng.uniform(-2, W)
            width = rng.uniform(0.35, 1.4)
            skew = rng.uniform(1.2, 3.0)
            poly = np.array([[x0, H], [x0 + width, H],
                             [x0 + width - skew, 0], [x0 - skew, 0]])
            ax.add_patch(Polygon(poly, closed=True, color=p['caustic'],
                                 alpha=rng.uniform(0.03, 0.075), zorder=0, lw=0))

        # sandy floor
        floor = np.linspace(0, W, 200)
        ridge = 0.55 + 0.18 * np.sin(floor * 0.8 + 1.2) + 0.09 * np.sin(floor * 2.3)
        ax.fill_between(floor, 0, ridge, color=p['sand'], alpha=0.35, zorder=0, lw=0)

        # rising bubbles
        n = 90
        bx = rng.uniform(0, W, n)
        by = rng.uniform(0, H, n)
        ax.scatter(bx, by, s=rng.uniform(1.5, 14, n), facecolors='none', edgecolors=p['foam'],
                   alpha=0.28, zorder=1, linewidths=0.7)

    # -- reef life ------------------------------------------------------------------------
    def node(self, ctx, nv):
        ax, rng, p, r, c = ctx.ax, ctx.rng, self.palette, nv.radius, nv.pos

        if nv.detail == 'simple':
            ax.add_patch(Circle(c, r * 0.7, color=p['coral'], alpha=0.85, zorder=4))
            ax.add_patch(Circle(c, r * 0.28, color=p['foam'], alpha=0.9, zorder=5))
        elif nv.is_a(PLACE):
            # coral head: stacked lobes with a bright crown
            for _ in range(14):
                a = rng.uniform(0, 2 * np.pi)
                d = rng.uniform(0, r * 0.72)
                lobe = np.asarray(c) + d * np.array([np.cos(a), np.sin(a)])
                ax.add_patch(Circle(lobe, rng.uniform(r * 0.18, r * 0.34), color=p['coral_deep'],
                                    alpha=0.75, zorder=4))
            for _ in range(10):
                a = rng.uniform(0, 2 * np.pi)
                d = rng.uniform(0, r * 0.5)
                lobe = np.asarray(c) + d * np.array([np.cos(a), np.sin(a)])
                ax.add_patch(Circle(lobe, rng.uniform(r * 0.12, r * 0.22), color=p['coral'],
                                    alpha=0.85, zorder=5))
            ax.add_patch(Circle(c, r * 0.16, color=p['foam'], alpha=0.9, zorder=6))
        else:
            # anemone: radiating tentacles, count driven by degree
            ntent = int(np.clip(10 + 3 * nv.degree, 12, 40))
            for a in np.linspace(0, 2 * np.pi, ntent, endpoint=False):
                a += rng.normal(0, 0.05)
                curl = rng.uniform(0.28, 0.52)
                t = np.linspace(0, 1, 14)
                rr = r * (0.55 + 0.75 * t)
                aa = a + curl * t ** 2
                xs = c[0] + rr * np.cos(aa)
                ys = c[1] + rr * np.sin(aa)
                ax.plot(xs, ys, color=p['anemone'], lw=max(0.7, 1.7 * r), alpha=0.7, zorder=4,
                        solid_capstyle='round')
                ax.add_patch(Circle((xs[-1], ys[-1]), max(0.012, 0.035 * r), color=p['foam'],
                                    alpha=0.75, zorder=5))
            ax.add_patch(Circle(c, r * 0.52, color=p['coral_deep'], alpha=0.9, zorder=5))
            ax.add_patch(Circle(c, r * 0.34, color=p['coral'], alpha=0.95, zorder=5))
            ax.add_patch(Ellipse(c, r * 0.28, r * 0.16, color=p['foam'], alpha=0.85, zorder=6))

        if nv.label:
            ax.text(c[0], c[1] - r - 0.36, nv.label, color=p['foam'],
                    fontsize=float(np.clip(11 + 6 * r, 10, 18)), ha='center', va='top',
                    fontfamily=ctx.font, zorder=6)
        if nv.caption:
            ax.text(c[0], c[1] - r - 0.80, nv.caption, color=p['caustic'], alpha=0.7, fontsize=9.5,
                    style='italic', ha='center', va='top', fontfamily=ctx.font, zorder=6)

    # -- kelp -----------------------------------------------------------------------------
    def edge(self, ctx, ev):
        ax, p = ctx.ax, self.palette
        pts = ctx.wobble(ev.points, amplitude=0.22, cycles=2.2)   # design owns its geometry
        ax.plot(pts[:, 0], pts[:, 1], color=p['kelp'], lw=4.0, alpha=0.55, zorder=2,
                solid_capstyle='round')
        ax.plot(pts[:, 0], pts[:, 1], color=p['kelp_light'], lw=1.6, alpha=0.8, zorder=2,
                solid_capstyle='round')
        side = float(np.sign(ev.bow)) or 1.0
        for q, s in zip(pts[5:-6:9], pts[6:-5:9]):                # air bladders along the strand
            t = (s - q) / (np.linalg.norm(s - q) + 1e-9)
            ax.add_patch(Circle(q + np.array([-t[1], t[0]]) * 0.1 * side, 0.045,
                                color=p['kelp_light'], alpha=0.85, zorder=2))
        ctx.chevron(pts, color=p['foam'], alpha=0.75)
        if ev.show_label:
            ctx.curve_label(pts, ev.local, side=side, color=p['caustic'], alpha=0.85)

    # -- chrome ---------------------------------------------------------------------------
    def chrome(self, ctx, title, subtitle):
        ax, p = ctx.ax, self.palette
        W, H = ctx.bounds
        if title:
            ax.text(0.55, H - 0.55, title, color=p['foam'], fontsize=27, fontfamily=ctx.font,
                    va='top', zorder=6)
        if subtitle:
            ax.text(0.57, H - 1.18, subtitle, color=p['caustic'], fontsize=12.5, style='italic',
                    fontfamily=ctx.font, va='top', zorder=6)
        if ctx.signature:
            ax.text(W - 0.4, 0.42, ctx.signature, color=p['foam'], alpha=0.75,
                    fontsize=12, style='italic', ha='right', fontfamily=ctx.font, zorder=6)


DESIGN = Aquatic()
