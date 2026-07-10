# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.exceptions
'''
Store-layer exceptions.

Deliberately thin. The store layer reuses the model's vocabulary of failure rather than
minting parallel error types:

- a graph that is not present is a plain ``KeyError`` (mapping semantics);
- an id-space collision (node id vs assertion ``@id``) is the model's
  ``onya.graph.AssertionIdConflict``;
- a merge-rule violation is the model's ``onya.graph.GraphMergeError``.

``StoreError`` is only for conditions with no model-layer counterpart — an unusable backing
store (unknown on-disk schema version, corrupt lock, and the like).
'''

from __future__ import annotations


class StoreError(Exception):
    '''Base for store-layer failures with no model-layer equivalent.'''


class UnknownSchemaVersion(StoreError):
    '''
    Raised when opening a relational store whose recorded ``skeleton_hash_version`` (or
    overall schema version) is not one this build understands. Refusing to open is safer
    than silently reading rows whose structural identity was computed by a different
    algorithm.
    '''
    def __init__(self, found, expected):
        self.found = found
        self.expected = expected
        super().__init__(
            f'Unrecognized store schema version {found!r} (this build understands {expected!r}); '
            f'refusing to open. Rebuild the store or upgrade Onya.'
        )
