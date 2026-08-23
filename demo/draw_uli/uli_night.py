# SPDX-License-Identifier: Apache-2.0
'''
uli_night — ọ́nyà taken literally: the graph as a spider's orb web on an indigo night, in a palette
borrowed from uli body-and-wall painting (nzu chalk, ochre, terracotta, camwood, olive).

Everything here is data-driven off the graph the driver hands it: degree -> size, Person/Place ->
motif, name/description -> text, edge label -> ornament. Swap in a different Onya Literate file
and re-weave with zero code edits.
'''
import numpy as np
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path

SCHEMA = 'https://schema.org/'
PLACE = SCHEMA + 'Place'


class UliNight:
    name = 'uli_night'
    background_color = '#151d36'
    font = 'DejaVu Serif'
    signature = 'ọ́nyà úchè — a web of knowledge'
    palette = {
        'ground': '#151d36',
        'glow': '#243055',
        'chalk': '#efe6d0',      # nzu
        'ochre': '#d9a441',
        'terra': '#b5542e',
        'camwood': '#8e3b2e',
        'olive': '#7c8148',
        'charcoal': '#221c18',
    }

    # -- atmosphere -----------------------------------------------------------------------
    def background(self, ctx):
        ax, rng, p = ctx.ax, ctx.rng, self.palette
        W, H = ctx.bounds
        center = ctx.hub.pos

        for rr, aa in ((11, 0.05), (8, 0.06), (5.5, 0.07), (3.5, 0.08)):
            ax.add_patch(Circle(center, rr, color=p['glow'], alpha=aa, zorder=0))
        stars = rng.uniform([0, 0], [W, H], size=(140, 2))
        ax.scatter(stars[:, 0], stars[:, 1], s=rng.uniform(0.3, 2.4, 140), c=p['chalk'],
                   alpha=0.35, zorder=0, linewidths=0)

        moon = np.array([W - 1.5, H - 1.1])
        ax.add_patch(Circle(moon, 0.42, color=p['ochre'], alpha=0.85, zorder=1))
        ax.add_patch(Circle(moon + [0.16, 0.09], 0.38, color=p['ground'], zorder=1))
        for a in np.linspace(np.pi * 0.7, np.pi * 1.6, 9):
            ax.add_patch(Circle(moon + 0.55 * np.array([np.cos(a), np.sin(a)]), 0.025,
                                color=p['chalk'], alpha=0.6, zorder=1))

        # the orb web, spun about the hub node
        nspoke = 15
        angles = np.sort(rng.normal(np.linspace(0, 2 * np.pi, nspoke, endpoint=False), 0.06))
        reach = float(np.hypot(W, H) * 0.58)
        for a in angles:
            end = center + reach * np.array([np.cos(a), np.sin(a)])
            ax.plot([center[0], end[0]], [center[1], end[1]], color=p['chalk'], lw=0.55,
                    alpha=0.12, zorder=1)
        dew = []
        for ri, r in enumerate(np.geomspace(0.9, reach * 0.95, 14)):
            pts = [center + r * np.array([np.cos(a), np.sin(a)]) for a in angles]
            for i in range(len(pts)):
                ax.add_patch(self._sag(pts[i], pts[(i + 1) % len(pts)], center, p['chalk']))
            if ri % 3 == 1:
                dew += [q for q in pts if rng.random() < 0.35]
        for q in dew:
            ax.add_patch(Circle(q, rng.uniform(0.015, 0.035), color=p['chalk'], alpha=0.45,
                                zorder=1))

    @staticmethod
    def _sag(p0, p1, center, color, sag=0.10):
        mid = (p0 + p1) / 2
        ctrl = mid + sag * (center - mid)
        path = Path([tuple(p0), tuple(ctrl), tuple(p1)],
                    [Path.MOVETO, Path.CURVE3, Path.CURVE3])
        return PathPatch(path, fill=False, edgecolor=color, lw=0.5, alpha=0.13, zorder=1)

    # -- motifs ---------------------------------------------------------------------------
    def node(self, ctx, nv):
        ax, p, r, c = ctx.ax, self.palette, nv.radius, nv.pos
        ax.add_patch(Circle(c, r * 1.28, color=p['ground'], alpha=0.92, zorder=3))  # clear the web
        lw = float(np.clip(3.4 * r / 1.1, 1.1, 3.6))

        if nv.detail == 'simple':
            ring = p['olive'] if nv.is_a(PLACE) else p['terra']
            ax.add_patch(Circle(c, r, fc='none', ec=ring, lw=lw, alpha=0.95, zorder=4))
            ax.add_patch(Circle(c, r * 0.34, color=p['camwood'], zorder=4))
        elif nv.is_a(PLACE):
            ax.add_patch(Circle(c, r, fc='none', ec=p['olive'], lw=lw, alpha=0.95, zorder=4))
            self._dots(ax, c, r * 1.16, 16, 0.045, p['chalk'])       # chalk boundary
            self._dots(ax, c, r * 0.72, 8, 0.085, p['terra'])        # compound of huts
            ax.add_patch(Circle(c, r * 0.30, color=p['ochre'], zorder=4))   # the ilo
            ax.add_patch(Circle(c, r * 0.12, color=p['charcoal'], zorder=5))
        else:
            ax.add_patch(Circle(c, r, fc='none', ec=p['terra'], lw=lw, alpha=0.95, zorder=4))
            ax.add_patch(Circle(c, r * 0.74, fc='none', ec=p['ochre'], lw=lw * 0.6, alpha=0.95,
                                zorder=4))
            self._dots(ax, c, r * 0.88, max(10, 4 * nv.degree + 8), 0.035, p['chalk'])
            ax.add_patch(Circle(c, r * 0.42, color=p['camwood'], alpha=0.95, zorder=4))
            ax.add_patch(Circle(c, r * 0.16, color=p['chalk'], zorder=5))

        if nv.label:
            ax.text(c[0], c[1] - r - 0.34, nv.label, color=p['chalk'],
                    fontsize=float(np.clip(11 + 6 * r, 10, 18)), ha='center', va='top',
                    fontfamily=ctx.font, zorder=5)
        if nv.caption:
            ax.text(c[0], c[1] - r - 0.78, nv.caption, color=p['chalk'], alpha=0.55, fontsize=9.5,
                    style='italic', ha='center', va='top', fontfamily=ctx.font, zorder=5)

    @staticmethod
    def _dots(ax, c, r, n, size, color, alpha=0.9, z=4):
        for a in np.linspace(0, 2 * np.pi, n, endpoint=False):
            ax.add_patch(Circle(np.asarray(c) + r * np.array([np.cos(a), np.sin(a)]), size,
                                color=color, alpha=alpha, zorder=z))

    # -- threads --------------------------------------------------------------------------
    def edge(self, ctx, ev):
        ax, p, pts = ctx.ax, self.palette, ev.points
        ax.plot(pts[:, 0], pts[:, 1], color=p['chalk'], lw=2.0, alpha=0.85, zorder=2,
                solid_capstyle='round')
        side = float(np.sign(ev.bow)) or 1.0
        for q, s in zip(pts[4:-6:7], pts[5:-5:7]):        # uli dotted companion line
            t = (s - q) / (np.linalg.norm(s - q) + 1e-9)
            ax.add_patch(Circle(q + np.array([-t[1], t[0]]) * 0.14 * side, 0.032,
                                color=p['ochre'], alpha=0.9, zorder=2))
        ctx.chevron(pts, color=p['chalk'])
        if ev.show_label:
            ctx.curve_label(pts, ev.local, side=side, color=p['chalk'])

    # -- chrome ---------------------------------------------------------------------------
    def chrome(self, ctx, title, subtitle):
        ax, p = ctx.ax, self.palette
        W, H = ctx.bounds
        if title:
            ax.text(0.55, H - 0.55, title, color=p['chalk'], fontsize=27, fontfamily=ctx.font,
                    va='top', zorder=5)
        if subtitle:
            ax.text(0.57, H - 1.18, subtitle, color=p['ochre'], fontsize=12.5, style='italic',
                    fontfamily=ctx.font, va='top', zorder=5)
        if ctx.signature:
            ax.text(W - 0.4, 0.42, ctx.signature, color=p['chalk'], alpha=0.7,
                    fontsize=12, style='italic', ha='right', fontfamily=ctx.font, zorder=5)


DESIGN = UliNight()
