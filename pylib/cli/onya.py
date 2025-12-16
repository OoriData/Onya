# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.cli.onya

'''
Onya CLI.

This CLI is intentionally simple: read Onya Literate (`.onya`) source text,
build a graph, then emit another representation such as Mermaid or Graphviz DOT.

Implementation notes:
- Uses `fire` for argument processing (per project conventions).
- Avoids `argparse` and keeps defaults aligned with serializer defaults.
'''

from __future__ import annotations

import glob
import sys
from pathlib import Path
from typing import TextIO

from onya.__about__ import __version__
from onya.serial.literate_lex import LiterateParser


def _looks_like_glob(filespec: str) -> bool:
    return any(ch in filespec for ch in ('*', '?', '[', ']'))


def _expand_filespec(filespec: str) -> list[Path]:
    '''
    Expand a filespec into concrete file paths.

    - `-` means stdin.
    - Globs are expanded using Python's glob module.
    - A directory is expanded to `**/*.onya`.
    '''
    if filespec == '-':
        return []

    p = Path(filespec)
    if p.exists() and p.is_dir():
        matches = glob.glob(str(p / '**' / '*.onya'), recursive=True)
        return [Path(x) for x in sorted(matches) if Path(x).is_file()]

    if _looks_like_glob(filespec):
        return [Path(x) for x in sorted(glob.glob(filespec, recursive=True)) if Path(x).is_file()]

    return [p]


def _infer_format(*, mermaid: bool, dot: bool, out: str | None) -> str:
    if mermaid and dot:
        raise ValueError('Choose at most one of --mermaid or --dot')
    if mermaid:
        return 'mermaid'
    if dot:
        return 'dot'

    if out and out not in ('-', ''):
        out_l = out.lower()
        if out_l.endswith('.dot'):
            return 'dot'
        if out_l.endswith('.mmd') or out_l.endswith('.mermaid'):
            return 'mermaid'

    return 'mermaid'  # Default, since it's easy to view via `mermaid.live`


def _open_output(out: str | None) -> TextIO:
    if not out or out == '-':
        return sys.stdout
    return open(out, 'w', encoding='utf-8')


def convert(filespec: str,
            *,
            mermaid: bool = False,
            dot: bool = False,
            out: str | None = '-',
            base: str | None = None,
            propertybase: str | None = None,
            rankdir: str = 'TB',
            show_properties: bool = True,
            show_types: bool = True,
            show_edge_labels: bool = True,
            show_edge_annotations: bool = True,
            document_source_assertions: bool = False,
            encoding: str = 'utf-8'):
    '''
    Convert Onya Literate input to another format.

    Args:
        filespec: Path, directory, glob, or '-' for stdin.
        mermaid: Emit Mermaid flowchart markup (`.mmd`-style text).
        dot: Emit Graphviz DOT.
        out: Output file path, or '-' for stdout.
        base/propertybase/rankdir/show_*: Passed to the target serializer.
        document_source_assertions: If set, parser adds @source provenance annotations.
        encoding: Text encoding used to read input files (ignored for stdin).

    Examples:
        onya convert test/resource/schemaorg/thingsfallapart.onya --mermaid
        onya convert test/resource/schemaorg/thingsfallapart.onya --dot --out /tmp/out.dot
        onya convert 'test/resource/schemaorg/*.onya' --dot > merged.dot
        cat file.onya | onya convert - --mermaid
    '''
    fmt = _infer_format(mermaid=mermaid, dot=dot, out=out)
    paths = _expand_filespec(filespec)

    parser = LiterateParser(document_source_assertions=document_source_assertions, encoding=encoding)

    graph_obj = None
    doc_iris: list[str] = []

    if filespec == '-':
        lit_text = sys.stdin.read()
        result = parser.parse(lit_text, graph_obj=graph_obj, encoding=encoding)
        graph_obj = result.graph
        if result.doc_iri:
            doc_iris.append(result.doc_iri)
    else:
        if not paths:
            raise FileNotFoundError(f'No files matched filespec: {filespec!r}')

        for p in paths:
            if not p.exists():
                raise FileNotFoundError(str(p))
            lit_text = p.read_text(encoding=encoding)
            result = parser.parse(lit_text, graph_obj=graph_obj, encoding=encoding)
            graph_obj = result.graph
            if result.doc_iri:
                doc_iris.append(result.doc_iri)

    if graph_obj is None:
        raise RuntimeError('No input was read')

    # Serializer selection is intentionally explicit (keeps CLI help obvious).
    if fmt == 'dot':
        from onya.serial import graphviz as emitter
        emit_kwargs = dict(
            base=base,
            propertybase=propertybase,
            rankdir=rankdir,
            show_properties=show_properties,
            show_types=show_types,
            show_edge_labels=show_edge_labels,
            show_edge_annotations=show_edge_annotations,
        )
    else:
        from onya.serial import mermaid as emitter
        emit_kwargs = dict(
            base=base,
            propertybase=propertybase,
            rankdir=rankdir,
            show_properties=show_properties,
            show_types=show_types,
            show_edge_labels=show_edge_labels,
            show_edge_annotations=show_edge_annotations,
        )

    fp = _open_output(out)
    try:
        emitter.write(graph_obj, out=fp, **emit_kwargs)
        if fp is not sys.stdout:
            fp.write('\n')
    finally:
        if fp is not sys.stdout:
            fp.close()

    # If writing to stdout, keep the CLI quiet. If writing to a file, a small hint helps.
    if out and out != '-':
        doc_hint = f'  # docs: {", ".join(doc_iris)}' if doc_iris else ''
        sys.stderr.write(f'Wrote {fmt} to {out}{doc_hint}\n')


def version() -> str:
    '''Return Onya version.'''
    return __version__


class _CLI:
    '''
    Fire command surface.

    We keep this thin and delegate to module functions; this also makes it easier
    to test `convert()` without needing to emulate argv parsing.
    '''
    convert = staticmethod(convert)
    version = staticmethod(version)


def main():
    '''
    Console script entry point.
    '''
    import fire

    fire.Fire(_CLI)

