# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.viz

'''
Onya visualization: expression-layer projections of a graph — Mermaid, Graphviz DOT, and the
networkx analytics bridge. These are views onto the data for rendering and analysis, not
serializations of Onya itself (that's `onya.serial`); layering matches `onya.serial`: each module
here imports the core (`onya.graph`, `onya.interp`, `onya.util`) and never the reverse.
'''
