# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.mermaid (legacy alias)

'''
Legacy import path. Mermaid projection now lives in `onya.viz.mermaid` — Mermaid/Graphviz/nx
are expression-layer views for rendering and analysis, not serializations of Onya itself, so
they no longer belong under `onya.serial`. This module re-exports `onya.viz.mermaid` for
backward compatibility and will be removed in a future release; update imports to
`from onya.viz import mermaid`.
'''
import warnings

from onya.viz.mermaid import *  # noqa: F401,F403
from onya.viz.mermaid import __all__  # noqa: F401

warnings.warn(
    "'onya.serial.mermaid' has moved to 'onya.viz.mermaid'; the 'onya.serial.mermaid' alias "
    'will be removed in a future release.',
    DeprecationWarning,
    stacklevel=2,
)
