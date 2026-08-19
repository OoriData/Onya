#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# demo/draw_uli/onya_draw.py
'''
onya_draw — a small, general-purpose CLI for the draw_uli renderer prototype (Onya issue #33):
render *any* Onya Literate (`.onya`/`.onya.md`) file through a pluggable Design, not just the
two bundled reference graphs. Not a supported library API — see `driver.py`'s module docstring
and `README.md` in this directory for status.

Title, subtitle, and the signature/colophon line come from the graph's own `@docheader`
(`schema:headline` / `schema:alternativeHeadline` / a `schema:comment` tagged `keywords:
decoration` — see `driver._docheader_text`) unless overridden here. Hand-tuned node position
anchors have no natural home in the graph itself, so they're read from an optional TOML sidecar
instead (see `control.py`) rather than hard-coded in a script.

Usage (from this directory, so the sibling driver/design/control modules resolve):
    python onya_draw.py things_fall_apart.onya.md --control things_fall_apart.control.toml
    python onya_draw.py boulder.onya.md --design flatirons
    python onya_draw.py mygraph.onya --design aquatic --title "Custom Title" --no-signature
'''
import argparse
import sys
from pathlib import Path

from onya.graph import graph
from onya.serial.literate import LiterateParser

import control
from driver import BUILTIN_DESIGNS, draw, save


def build_parser():
    ap = argparse.ArgumentParser(
        description='Render an Onya Literate file through a draw_uli Design.')
    ap.add_argument('input', help='.onya / .onya.md file to render')
    ap.add_argument('--design', default='uli_night', choices=sorted(BUILTIN_DESIGNS),
                     help='Design to render through (default: %(default)s)')
    ap.add_argument('--out', help='Output image path (default: render_<input stem>.png)')
    ap.add_argument('--seed', type=int, help="RNG/layout seed; overrides the control file's")
    ap.add_argument('--title', help="Override the graph's schema:headline")
    ap.add_argument('--subtitle', help="Override the graph's schema:alternativeHeadline")
    sig = ap.add_mutually_exclusive_group()
    sig.add_argument('--signature', help='Override the signature/colophon text')
    sig.add_argument('--no-signature', action='store_true', help='Suppress the signature line')
    ap.add_argument('--size-by', help='Property IRI to size nodes by (default: degree)')
    ap.add_argument('--label-top-k', type=int,
                     help='How many nodes to label (default: a size heuristic)')
    ap.add_argument('--figsize', type=float, nargs=2, metavar=('W', 'H'),
                     help="Figure size in inches; overrides the control file's")
    ap.add_argument('--control', help='Optional TOML sidecar (pos/seed/figsize/... — see control.py)')
    ap.add_argument('--include-document', action='store_true',
                     help='Draw the onya:Document bookkeeping node too (default: omit it)')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = control.load(args.control)

    g = graph()
    with open(args.input, encoding='utf-8') as f:
        result = LiterateParser().parse(f.read(), g)

    # Auto-derive display prefixes from the file's own docheader convention -- no manual
    # bookkeeping needed for node-id / edge-label compaction in labels and captions.
    prefixes = dict(result.prefixes or {})
    if result.schema:
        prefixes['schema'] = result.schema

    fig = draw(
        g, args.design,
        seed=args.seed if args.seed is not None else cfg.get('seed', 0),
        pos=control.expand_pos(cfg, result.nodebase),
        size_by=args.size_by or cfg.get('size_by'),
        figsize=tuple(args.figsize) if args.figsize else tuple(cfg.get('figsize', (16, 10))),
        prefixes=prefixes or None,
        include_document=args.include_document,
        title=args.title,
        subtitle=args.subtitle,
        label_top_k=args.label_top_k if args.label_top_k is not None else cfg.get('label_top_k'),
        signature=False if args.no_signature else args.signature,
    )
    out = args.out or f'render_{Path(args.input).name.split(".")[0]}.png'
    save(fig, out)
    print(f'Generated: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
