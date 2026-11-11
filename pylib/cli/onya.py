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

import re
import sys
# from pathlib import Path
from typing import TextIO

from onya.__about__ import __version__
from onya.serial.literate import (
    DanglingTargetError, LiterateParser, LiterateParseError, expand_paths, report_dangling, undeclared_refs,
)


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
            nodebase: str | None = None,
            schema: str | None = None,
            rankdir: str = 'TB',
            show_properties: bool = True,
            show_types: bool = True,
            show_edge_labels: bool = True,
            show_edge_annotations: bool = True,
            document_source_assertions: bool = False,
            encoding: str = 'utf-8',
            lenient_arrows: bool = False,
            on_dangling: str = 'ignore',
            allow: str | list | tuple | None = None):
    '''
    Convert Onya Literate input to another format.

    Args:
        filespec: Path, directory (recursive; `.onya` and `.onya.md`), glob, or '-' for stdin.
        mermaid: Emit Mermaid flowchart markup (`.mmd`-style text).
        dot: Emit Graphviz DOT.
        out: Output file path, or '-' for stdout.
        nodebase/schema/rankdir/show_*: Passed to the target serializer.
        document_source_assertions: If set, parser adds @source provenance annotations.
        encoding: Text encoding used to read input files (ignored for stdin).
        lenient_arrows: If set, accept a stray edge arrow (e.g. `➡`, `=>`), warn, and
            continue instead of erroring with EdgeArrowError.
        on_dangling: What to do about edge targets no node block declares (often typos):
            'ignore' (default), 'warn', or 'error' (exit non-zero). Judged after all files are read.
        allow: Targets that may stay undeclared: an IRI prefix, or several separated by commas.

    Examples:
        onya convert test/resource/schemaorg/thingsfallapart.onya --mermaid
        onya convert test/resource/schemaorg/thingsfallapart.onya --dot --out /tmp/out.dot
        onya convert kg/ --mermaid --on_dangling=error --allow=https://orcid.org/
        onya convert 'test/resource/schemaorg/*.onya' --dot > merged.dot
        cat file.onya | onya convert - --mermaid
    '''
    fmt = _infer_format(mermaid=mermaid, dot=dot, out=out)
    if on_dangling not in ('ignore', 'warn', 'error'):
        raise ValueError(f"on_dangling must be 'ignore', 'warn' or 'error', not {on_dangling!r}")
    paths = [] if filespec == '-' else expand_paths(filespec)

    parser = LiterateParser(document_source_assertions=document_source_assertions, encoding=encoding,
                            lenient_arrows=lenient_arrows)

    graph_obj = None
    doc_iris: list[str] = []
    dangling_edges: list = []  # edges to nodes undeclared when their file was read; re-judged at the end

    def _parse(text: str, source: str):
        # A friendly parse diagnostic (stray arrow, bad node id, unclosed [Type], preamble
        # prose, ...) carries an actionable message; show just that (not a traceback) and exit
        # non-zero. `--lenient_arrows` downgrades the arrow case to a warning instead.
        try:
            return parser.parse(text, graph_obj=graph_obj, encoding=encoding)
        except LiterateParseError as exc:
            sys.stderr.write(f'{source}: {exc}\n')
            raise SystemExit(2)

    if filespec == '-':
        lit_text = sys.stdin.read()
        result = _parse(lit_text, '<stdin>')
        graph_obj = result.graph
        dangling_edges += [d.edge for d in result.dangling]
        if result.doc_iri:
            doc_iris.append(result.doc_iri)
    else:
        if not paths:
            raise FileNotFoundError(f'No files matched filespec: {filespec!r}')

        for p in paths:
            if not p.exists():
                raise FileNotFoundError(str(p))
            lit_text = p.read_text(encoding=encoding)
            result = _parse(lit_text, str(p))
            graph_obj = result.graph
            dangling_edges += [d.edge for d in result.dangling]
            if result.doc_iri:
                doc_iris.append(result.doc_iri)

    if graph_obj is None:
        raise RuntimeError('No input was read')

    if on_dangling != 'ignore':
        if isinstance(allow, str):
            allow = [a.strip() for a in allow.split(',') if a.strip()]
        try:
            report_dangling(undeclared_refs(dangling_edges, allow), on_dangling)
        except DanglingTargetError as exc:
            sys.stderr.write(f'{exc}\n')
            raise SystemExit(2)

    # Serializer selection is intentionally explicit (keeps CLI help obvious).
    emit_kwargs = dict(
        nodebase=nodebase,
        schema=schema,
        rankdir=rankdir,
        show_properties=show_properties,
        show_types=show_types,
        show_edge_labels=show_edge_labels,
        show_edge_annotations=show_edge_annotations,
    )
    if fmt == 'dot':
        from onya.viz import graphviz as emitter
    else:
        from onya.viz import mermaid as emitter

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


def _load(spec: str, encoding: str):
    '''Read a filespec (or '-' for stdin) into one merged graph, tracking locations; a parse error exits 2.'''
    from onya.serial.literate import read_many
    try:
        if spec == '-':
            from onya.serial.literate import read
            from onya.graph import graph
            g = graph()
            read(sys.stdin.read(), g, track_locations=True)
            return g
        return read_many(spec, merge=True, encoding=encoding, track_locations=True).graph
    except LiterateParseError as exc:
        sys.stderr.write(f'{spec}: {exc}\n')
        raise SystemExit(2)


def validate(filespec: str,
             *,
             shapes: str | None = None,
             strict: bool = False,
             dangling: bool = False,
             allow: str | list | tuple | None = None,
             against: str | None = None,
             store: str | None = None,
             graph: str | list | tuple | None = None,
             encoding: str = 'utf-8'):
    '''
    Check Onya Literate input against its shapes (see doc/design-shapes.md) and print the findings.

    Args:
        filespec: Path, directory (recursive; `.onya` and `.onya.md`), glob, or '-' for stdin.
        shapes: Where the `@Class` / `@Property` declarations are, as a filespec; by default, the input itself.
        strict: Fail on warnings too (a typo'd `@term`, a `@severity: warning` shape, a use of a `@deprecated` term).
        dangling: Also report edge targets that no node block declares.
        allow: Targets that may stay undeclared: an IRI prefix, or several separated by commas.
        against: Treat the input as a proposed change (a fragment) and check it as if merged into this base, a
            filespec. Only findings on the nodes the input names are reported; shapes come from the base unless
            --shapes is given.
        store: Like --against, with the base held in this store URL (`sqlite:app.db`, `postgresql://...`); needs
            --graph. Only the part of the stored graph the input touches is read.
        graph: With --store, the stored graph name, or several separated by commas (their union is the base).
        encoding: Text encoding used to read input files (ignored for stdin).

    Exit status: 0 if clean, 2 if there are error findings (or warnings, with --strict), or on a
    parse error. Findings name the line they came from.

    Examples:
        onya validate kg/
        onya validate kg/ --shapes=shapes/ --dangling --allow=https://orcid.org/ --strict
        onya validate proposed.onya --against=kg/
        onya validate proposed.onya --store=sqlite:kg.db --graph=http://example.org/kg
    '''
    from onya.shape import load_shapes, validate as check, validate_against_store

    if against and store:
        raise SystemExit('Pass --against (a filespec) or --store (with --graph), not both.')
    if store and not graph:
        raise SystemExit('--store needs --graph: the name of the stored graph (or several, separated by commas).')
    g = _load(filespec, encoding)
    if isinstance(allow, str):
        allow = [a.strip() for a in allow.split(',') if a.strip()]
    sh = load_shapes(_load(shapes, encoding)) if shapes else None
    if store:
        names = [x.strip() for x in graph.split(',')] if isinstance(graph, str) else list(graph)

        async def run():
            from onya.store import connect
            async with await connect(store) as st:
                return await validate_against_store(g, st, names, shapes=sh, dangling=dangling, allow=allow)
        import asyncio
        report = asyncio.run(run())
    else:
        report = check(g, sh, dangling=dangling, allow=allow, against=_load(against, encoding) if against else None)
    for f in report.findings:
        print(f)
    failed = report.findings if strict else report.errors
    if failed:
        sys.stderr.write(f'{len(report.errors)} error(s), {len(report.warnings)} warning(s)\n')
        raise SystemExit(2)


def project(filespec: str,
            cls: str,
            *,
            shapes: str | None = None,
            to: str | None = None,
            dialect: str = 'postgres',
            arrays: bool = False,
            encoding: str = 'utf-8'):
    '''
    Project the graph into relational tables, derived from its shapes (see doc/design-circum.md).
    With `--to`, create and fill the tables there; without it, print the `CREATE TABLE` statements.

    Args:
        filespec: Path, directory (recursive; `.onya` and `.onya.md`), glob, or '-' for stdin.
        cls: IRI (or CURIE) of the class whose instances become rows; classes its edges point at come too.
        shapes: Where the `@Class` / `@Property` declarations are, as a filespec; by default, the input itself.
        to: Where to write: `sqlite:PATH` or `postgresql://...` (needs `onya[postgres]`).
        dialect: `postgres` or `sqlite`, for the printed DDL (without --to).
        arrays: Put multi-valued properties in array columns (PostgreSQL) rather than child tables.
        encoding: Text encoding used to read input files (ignored for stdin).

    Exit status: 0 on success, 2 if a value does not fit its column (the message names the node and line)
    or on a parse error; nothing is written in that case.

    Examples:
        onya project kg/ https://example.org/Person
        onya project kg/ https://example.org/Person --to=sqlite:circumstances.db
    '''
    import asyncio
    from onya.circum import CircumError, ddl, from_shapes, materialize

    g = _load(filespec, encoding)
    try:
        p = from_shapes(g, cls, shapes=_load(shapes, encoding) if shapes else None, array_columns=arrays)
        if to is None:
            print(ddl(p, dialect))
            return
        print(asyncio.run(materialize(to, p, g)))
    except CircumError as exc:
        for problem in exc.problems:
            sys.stderr.write(f'{problem}\n')
        raise SystemExit(2)


def version() -> str:
    '''Return Onya version.'''
    return __version__


def catalog(filespec: str, *, encoding: str = 'utf-8'):
    '''
    List the sidecars a graph declares (`@Sidecar`), each with its table and the properties that are held in it.

    Args:
        filespec: Path, directory (recursive; `.onya` and `.onya.md`), glob, or '-' for stdin.
        encoding: Text encoding used to read input files (ignored for stdin).

    Exit status: 2 if a declaration is unsound (a `@circumQuery` that names no `@Sidecar`), or on a parse error.

    Example:
        onya catalog kg/
    '''
    from onya.circum import CircumError, catalog as sidecars

    try:
        found = sidecars(_load(filespec, encoding))
    except CircumError as e:
        sys.stderr.write('\n'.join(e.problems) + '\n')
        raise SystemExit(2)
    for sc in found:
        facts = [f'system: {_tail(sc.system)}' if sc.system else '', f'table: {sc.table}' if sc.table else '',
                 f'sensitivity: {sc.sensitivity}' if sc.sensitivity else '']
        print('  '.join(x for x in [_tail(sc.id), sc.label or '', *facts] if x))
        for p in sc.holds:
            shape = p.shape
            where = ' | '.join(sorted(_tail(c) for c in shape.applies_to)) if shape else ''
            to = ' | '.join(sorted(_tail(c) for c in shape.range)) if shape else ''
            span = f' ({where} -> {to})' if where and to else f' ({where or to})' if where or to else ''
            print(f'  holds: {_tail(p.label)}{span}')


def _tail(iri) -> str:
    return re.split(r'[/#]', str(iri).rstrip('/#'))[-1]


class _CLI:
    '''
    Fire command surface.

    We keep this thin and delegate to module functions; this also makes it easier
    to test `convert()` without needing to emulate argv parsing.
    '''
    convert = staticmethod(convert)
    validate = staticmethod(validate)
    project = staticmethod(project)
    catalog = staticmethod(catalog)
    version = staticmethod(version)


def main():
    '''
    Console script entry point.
    '''
    import fire

    fire.Fire(_CLI)
