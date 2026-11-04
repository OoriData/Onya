# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.locations
'''
Source locations for diagnostics: where in a document a node or assertion was written.

The graph itself stores no locations (a slot per assertion would cost memory on every graph,
diagnosed or not). They are an opt-in side table, filled when a read is asked to
(`read(..., track_locations=True)`) and consulted by diagnostics through `graph.locate()`.
'''

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    '''
    Where something was written: the 1-based `lineno` and the text of that `line` in the document
    `doc_iri` (None if it declared none). `source` is the file path when read via `read_many`.
    A multi-line value is located at its first line.
    '''
    doc_iri: str | None
    lineno: int
    line: str
    source: str | None = None

    def __str__(self) -> str:
        return f'{self.source or self.doc_iri or "<text>"}:{self.lineno}'


NOT_TRACKED = '(location not tracked)'


def describe(location: 'Location | None') -> str:
    '''`location` as a short suffix for a diagnostic message: `(at doc:12)`, or `(location not tracked)`.'''
    return f'(at {location})' if location is not None else NOT_TRACKED


class Locations:
    '''
    A table of `Location`s keyed by object identity (nodes and assertions hash by identity, and
    are only ever looked up by the very object, never an equal one). The table holds a reference to
    each object it keys, so an id can never be reused by another object while the entry lives.
    '''
    def __init__(self):
        self._table: dict[int, tuple[object, Location]] = {}

    def add(self, obj, location: Location, *, first: bool = False) -> None:
        '''Record `location` for `obj`; with `first`, keep an existing entry rather than replace it.'''
        if first and id(obj) in self._table:
            return
        self._table[id(obj)] = (obj, location)

    def get(self, obj, default=None):
        entry = self._table.get(id(obj))
        return entry[1] if entry is not None else default

    def __getitem__(self, obj) -> Location:
        entry = self._table.get(id(obj))
        if entry is None:
            raise KeyError(obj)
        return entry[1]

    def __contains__(self, obj) -> bool:
        return id(obj) in self._table

    def __len__(self) -> int:
        return len(self._table)

    def update(self, other: 'Locations') -> None:
        for obj, loc in other._table.values():
            self.add(obj, loc)

    def __repr__(self) -> str:
        return f'{type(self).__name__} with {len(self)} entries'
