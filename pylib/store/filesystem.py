# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.store.filesystem
'''
Filesystem store backend — one Onya Literate file per named graph.

This is the default backend and the executable specification the SQL backends are tested
against: ``put(merge=True)`` is literally *parse the existing file, union in memory via the
model's merge, re-serialize*, so a round trip through it is by construction indistinguishable
from an in-memory graph union. It doubles as the zero-dependency fake for downstream test
suites.

Layout: ``<root>/<slug>.onya`` where ``<slug>`` is a filesystem-safe, digest-suffixed
rendering of the graph IRI. The slug is *write-only* — the authoritative name is the file's
own ``@docheader`` ``@document``; on read we trust that, never the filename. ``.onya.md`` is
accepted on read (for Markdown-editor affordances); we always emit ``.onya``.

Concurrency posture: a ``.lock`` sidecar created with ``O_CREAT | O_EXCL`` and bounded
retry serializes writers to a single graph file. This is a **testing and small-tool
backend**, not a contended one — for real concurrency reach for SQLite or PostgreSQL.
Writes are atomic (temp file + ``os.replace``).
'''

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import time
from pathlib import Path

from amara.iri import I

from onya.graph import graph
from onya.serial.literate import LiterateParser, write as literate_write
from onya.store.exceptions import StoreError

# Deterministic slug: safe characters from the IRI, truncated, plus a short digest of the
# full IRI so distinct IRIs that sanitize to the same prefix never collide. Deterministic so
# the file for a name can be located directly, with a scan fallback for externally-renamed files.
_SAFE_RE = re.compile(r'[^A-Za-z0-9._-]+')
_SLUG_MAX = 80

# Docheader @document line, for cheaply reading a file's authoritative name without a full parse.
_DOC_RE = re.compile(r'^\s*\*\s*@document\s*:\s*(\S+)', re.MULTILINE)

_LOCK_RETRIES = 100
_LOCK_SLEEP = 0.02  # seconds between lock attempts (~2s bounded wait)


def _slug(name: str) -> str:
    safe = _SAFE_RE.sub('_', name).strip('_')[:_SLUG_MAX] or 'graph'
    digest = hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]
    return f'{safe}-{digest}'


def _url_to_root(url: str) -> Path:
    '''Turn a ``file:`` URL into a root directory path. Accepts ``file:/abs``, ``file:rel``,
    and ``file:///abs`` forms.'''
    raw = url.partition(':')[2]
    if raw.startswith('//'):  # file://host/path or file:///abs -> drop the authority slashes
        raw = raw[2:]
    if not raw:
        raise ValueError(f'file: URL {url!r} has no path')
    return Path(raw)


class FileStore:
    '''A directory of Onya Literate files, one per named graph. Satisfies ``GraphStore``.'''

    def __init__(self, root: Path):
        self.root = Path(root)

    # --- construction / lifecycle ---------------------------------------------------

    @classmethod
    async def from_url(cls, url: str) -> 'FileStore':
        root = _url_to_root(url)
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        return cls(root)

    async def __aenter__(self) -> 'FileStore':
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    # --- path helpers ---------------------------------------------------------------

    def _write_path(self, name: str) -> Path:
        return self.root / f'{_slug(name)}.onya'

    def _existing_path(self, name: str) -> Path | None:
        slug = _slug(name)
        for suffix in ('.onya', '.onya.md'):
            p = self.root / f'{slug}{suffix}'
            if p.exists():
                return p
        return None

    def _lock_path(self, name: str) -> Path:
        return self.root / f'{_slug(name)}.lock'

    # --- Onya Literate (de)serialization --------------------------------------------

    @staticmethod
    def _to_literate(g: graph, name: str) -> str:
        out = io.StringIO()
        literate_write(g, out, document=str(name))
        return out.getvalue()

    @staticmethod
    def _from_literate(text: str) -> graph:
        g = graph()
        LiterateParser().parse(text, g)
        return g

    # --- locking (blocking; called inside to_thread) --------------------------------

    def _acquire_lock(self, name: str):
        lock = self._lock_path(name)
        for _ in range(_LOCK_RETRIES):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return lock
            except FileExistsError:
                time.sleep(_LOCK_SLEEP)
        raise StoreError(
            f'Could not acquire lock {lock} after {_LOCK_RETRIES} tries; a stale .lock may '
            f'need manual removal (this backend is not built for contended writers).'
        )

    @staticmethod
    def _release_lock(lock: Path) -> None:
        try:
            lock.unlink()
        except FileNotFoundError:  # pragma: no cover - lost lock; nothing to release
            pass

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_name(path.name + f'.tmp-{os.getpid()}')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)  # atomic on POSIX and Windows for same-dir replace

    # --- blocking put implementation (runs in a worker thread) ----------------------

    def _put_blocking(self, name: str, g: graph, merge: bool) -> None:
        lock = self._acquire_lock(name)
        try:
            if merge:
                # "Parse existing, union in memory, re-serialize." The incoming graph is copied
                # through a serialize/parse round trip first, so (a) the caller's graph is never
                # mutated by union's reparenting, and (b) same-`@id` assertions across the two
                # sources go through the *model* union (Rule 1 merge) rather than the parser's
                # one-document repeated-`@id` guard.
                stored = graph()
                existing = self._existing_path(name)
                if existing is not None:
                    with open(existing, encoding='utf-8') as f:
                        LiterateParser().parse(f.read(), stored)
                incoming = self._from_literate(self._to_literate(g, name))
                stored.union(incoming)
                text = self._to_literate(stored, name)
            else:
                g.validate_id_space()  # wholesale replace, but never persist an id-space collision
                text = self._to_literate(g, name)
            self._atomic_write(self._write_path(name), text)
        finally:
            self._release_lock(lock)

    # --- GraphStore -----------------------------------------------------------------

    async def put(self, name: I | str, g: graph, *, merge: bool = True) -> None:
        await asyncio.to_thread(self._put_blocking, str(name), g, merge)

    async def get(self, name: I | str) -> graph:
        name = str(name)

        def _read() -> graph:
            path = self._existing_path(name)
            if path is None:
                raise KeyError(name)
            with open(path, encoding='utf-8') as f:
                return self._from_literate(f.read())

        return await asyncio.to_thread(_read)

    async def drop(self, name: I | str) -> None:
        name = str(name)

        def _drop() -> None:
            slug = _slug(name)
            removed = False
            for suffix in ('.onya', '.onya.md'):
                p = self.root / f'{slug}{suffix}'
                if p.exists():
                    p.unlink()
                    removed = True
            if not removed:
                raise KeyError(name)

        await asyncio.to_thread(_drop)

    async def names(self):
        def _scan() -> list[str]:
            found: list[str] = []
            seen: set[str] = set()
            for pattern in ('*.onya', '*.onya.md'):
                for p in sorted(self.root.glob(pattern)):
                    try:
                        text = p.read_text(encoding='utf-8')
                    except OSError:  # pragma: no cover - race with a concurrent drop
                        continue
                    m = _DOC_RE.search(text)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        found.append(m.group(1))
            return found

        for name in await asyncio.to_thread(_scan):
            yield I(name)
