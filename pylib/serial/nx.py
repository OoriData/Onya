# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.nx (legacy alias)

'''
Legacy import path. The networkx projection now lives in `onya.viz.nx` — Mermaid/Graphviz/nx
are expression-layer views for rendering and analysis, not serializations of Onya itself, so
they no longer belong under `onya.serial`. This module re-exports `onya.viz.nx` for backward
compatibility and will be removed in a future release; update imports to `from onya.viz import nx`.

Importing this shim does not itself require networkx (the re-exported functions stay lazy,
per `onya.viz.nx`); only calling `to_networkx`/`write_back` does.
'''
import warnings

from onya.viz.nx import *  # noqa: F401,F403
from onya.viz.nx import __all__  # noqa: F401

warnings.warn(
    "'onya.serial.nx' has moved to 'onya.viz.nx'; the 'onya.serial.nx' alias will be removed in "
    'a future release.',
    DeprecationWarning,
    stacklevel=2,
)
