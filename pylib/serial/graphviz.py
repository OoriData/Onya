# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.graphviz (legacy alias)

'''
Legacy import path. Graphviz DOT projection now lives in `onya.viz.graphviz` — Mermaid/Graphviz/nx
are expression-layer views for rendering and analysis, not serializations of Onya itself, so
they no longer belong under `onya.serial`. This module re-exports `onya.viz.graphviz` for
backward compatibility and will be removed in a future release; update imports to
`from onya.viz import graphviz`.
'''
import warnings

from onya.viz.graphviz import *  # noqa: F401,F403
from onya.viz.graphviz import __all__  # noqa: F401

warnings.warn(
    "'onya.serial.graphviz' has moved to 'onya.viz.graphviz'; the 'onya.serial.graphviz' alias "
    'will be removed in a future release.',
    DeprecationWarning,
    stacklevel=2,
)
