# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.literate

"""
Serialize and deserialize between an Onya model and Onya Literate (Markdown)

see: SPEC.md (Onya Literate serialization)
"""

import re
import sys

from onya import I
from onya.util import compact_iri, namespace_for_curie, shorten_node_id
from onya.graph import AssertionIdConflict
from onya.terms import ONYA_INTERP, RESERVED_INTERP_NAMES
from onya.serial._literate_parse import (
    EdgeArrowError,
    InterpretationParseError,
    LiterateParser,
    NamespaceBaseError,
    ParseResult,
    SchemaPrefixConflict,
)

__all__ = [
    'read',
    'write',
    'longtext',
    'LiterateParser',
    'ParseResult',
    'SchemaPrefixConflict',
    'NamespaceBaseError',
    'InterpretationParseError',
    'EdgeArrowError',
    'AssertionIdConflict',
]


def longtext(t):
    '''
    Prepare long text to be e.g. included as an Onya literate property value,
    according to markdown rules

    Only use this function if you're Ok with possible whitespace-specific changes
    '''
    endswith_cr = t[-1] == '\n'
    new_t = t.replace('\n', '\n    ')
    if endswith_cr:
        new_t = new_t[:-5]
    return new_t


def _prefixes_for_write(schema: str | None, prefixes: dict[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for k, v in (prefixes or {}).items():
        result[k] = v if str(v).endswith('#') else namespace_for_curie(v)
    if schema:
        result['schema'] = namespace_for_curie(schema)
    return result


def _format_label(
    label,
    prefixes: dict[str, str],
    *,
    bracket_curie: bool = False,
) -> str:
    return compact_iri(str(label), prefixes, bracket=bracket_curie)


def _format_value(val, nodebase: str | None, prefixes: dict[str, str]) -> str:
    if isinstance(val, I):
        inner = shorten_node_id(val, nodebase)
        if inner != str(val):
            return inner
        return compact_iri(str(val), prefixes)
    s = str(val)
    if re.search(r'[\s:"\\]', s) or s == '':
        # Quote and escape so the parser's QuotedString (esc_char='\\') recovers the value
        # byte-for-byte. Multi-line values never reach here — they go via a text reference.
        esc = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{esc}"'
    return s


def _format_interp(interp, prefixes: dict[str, str]) -> str:
    '''
    Render an interpretation IRI back to `@as` name form: a reserved bare name for a
    Lightweight Types IRI, a declared abbreviation where one applies, else the full IRI.
    Pure model operation — never consults an interpretation registry (see pylib design).
    '''
    s = str(interp)
    prefix = str(ONYA_INTERP)
    if s.startswith(prefix):
        local = s[len(prefix):]
        if local in RESERVED_INTERP_NAMES:
            return local
    return compact_iri(s, prefixes)


def _write_prop_line(out, indent: str, label: str, value, nodebase, prefixes, textrefs: list) -> None:
    '''
    Write a property's ``* label: value`` line. A multi-line string value is emitted as a
    text reference (``* label:: _ltN``) with its content collected into ``textrefs`` for a
    trailing ``:_ltN = """..."""`` definition — the only value form the parser reads back
    across line boundaries.
    '''
    if isinstance(value, str) and '\n' in value:
        name = f'lt{len(textrefs)}'  # text-ref names must start with a letter (parser IDENT)
        textrefs.append((name, value))
        out.write(f'{indent}* {label}:: {name}\n')
    else:
        out.write(f'{indent}* {label}: {_format_value(value, nodebase, prefixes)}\n')


def _write_assertion(assertion, is_edge: bool, out, indent: str, nodebase, prefixes, bracket_curie: bool,
                     textrefs: list):
    '''Emit one assertion line, its ``@id`` / ``@as`` (if any), then recurse into its assertions.'''
    label = _format_label(assertion.label, prefixes, bracket_curie=bracket_curie)
    if is_edge:
        out.write(f'{indent}* {label} -> {shorten_node_id(assertion.target.id, nodebase)}\n')
    else:
        _write_prop_line(out, indent, label, assertion.value, nodebase, prefixes, textrefs)
    child_indent = indent + '    '
    if assertion.id is not None:
        out.write(f'{child_indent}* @id: {shorten_node_id(assertion.id, nodebase)}\n')
    # Emit `@as` for a set interpretation, at every depth (mirrors `@id`; the recursion below
    # carries it into nested assertions). Phase 1 is always inline — no header factoring.
    if getattr(assertion, 'interp', None) is not None:
        out.write(f'{child_indent}* @as: {_format_interp(assertion.interp, prefixes)}\n')
    # Recurse so nested properties AND nested edges round-trip at any depth
    _write_assertions(assertion, out, child_indent, nodebase, prefixes, bracket_curie, textrefs)


def _write_assertions(container, out, indent: str, nodebase, prefixes, bracket_curie: bool, textrefs: list):
    for prop in sorted(container.properties, key=lambda p: str(p.label)):
        _write_assertion(prop, False, out, indent, nodebase, prefixes, bracket_curie, textrefs)
    for edge in sorted(container.edges, key=lambda e: str(e.label)):
        _write_assertion(edge, True, out, indent, nodebase, prefixes, bracket_curie, textrefs)


def write(
    model,
    out=sys.stdout,
    *,
    document: str | None = None,
    nodebase: str | None = None,
    schema: str | None = None,
    prefixes: dict[str, str] | None = None,
    bracket_curie: bool = False,
    bracket_types: bool = False,
):
    '''
    Serialize an Onya graph to Onya Literate (Markdown).

    document -- @document IRI (document node is not written as a ``#`` block)
    nodebase -- @nodebase for relativizing node IDs in headers and edge targets
    schema -- @schema base IRI; also registers the ``schema`` CURIE prefix
    prefixes -- additional ``@iri`` prefix map (prefix name -> namespace base)
    bracket_curie -- if True, write labels as ``<prefix:local>`` instead of ``prefix:local``
    bracket_types -- if True, write types as ``[<prefix:Type>]`` with bracketed CURIEs
    '''
    all_prefixes = _prefixes_for_write(schema, prefixes)
    document_s = str(document) if document else None
    # Collected multi-line property values, emitted as `:name = """..."""` text-ref
    # definitions after the node blocks (the parser gathers these in a first pass, so their
    # position relative to the referencing lines does not matter).
    textrefs: list = []

    if document or nodebase or schema or prefixes:
        out.write('# @docheader\n\n')
        if document:
            out.write(f'* @document: {document}\n')
        if nodebase:
            out.write(f'* @nodebase: {nodebase}\n')
        if schema:
            out.write(f'* @schema: {schema}\n')
        extra = {k: v for k, v in sorted(all_prefixes.items()) if k != 'schema'}
        if extra:
            out.write('* @iri:\n')
            for k, v in extra.items():
                out.write(f'    * {k}: {v}\n')
        if document_s and document_s in model.nodes:
            # The document node is a first-class node: emit its assertions with the same full
            # path as body nodes (@id / @as / nesting / edges), just inside @docheader rather
            # than a `#` block (see SPEC § Document Header). The directives above are document
            # fields, not stored assertions, so there is no double-emission.
            _write_assertions(model.nodes[document_s], out, '', nodebase, all_prefixes,
                              bracket_curie, textrefs)
        out.write('\n')

    for nid in sorted(model.nodes.keys(), key=str):
        if document_s and str(nid) == document_s:
            continue
        node = model[nid]
        header_id = shorten_node_id(nid, nodebase)
        if node.types:
            types = sorted(node.types, key=str)
            type_parts = [
                _format_label(t, all_prefixes, bracket_curie=bracket_types)
                for t in types
            ]
            type_str = ' '.join(type_parts)
            out.write(f'# {header_id} [{type_str}]\n\n')
        else:
            out.write(f'# {header_id}\n\n')
        _write_assertions(node, out, '', nodebase, all_prefixes, bracket_curie, textrefs)
        out.write('\n')

    # Trailing text-reference definitions for any multi-line values emitted above.
    for name, value in textrefs:
        out.write(f':{name} = """{value}"""\n')
    return


def read(fp, g=None, *, document_source_assertions: bool = False, encoding: str = 'utf-8',
         merge: bool = False, lenient_arrows: bool = False):
    '''
    Read Onya Literate format from a file-like object (or text string) into a graph.

    fp -- file-like object with a ``.read()`` method, OR a ``str`` of Onya Literate source
    g -- graph to populate; if None, a new ``onya.graph.graph`` is created
    document_source_assertions -- if True, tag each created assertion with an @source sub-property
    encoding -- character encoding hint passed through to the parser
    merge -- convenience: when True, call ``graph.merge()`` once after reading. Defaults to
        False (parsing accumulates distinct occurrences; merge stays on-demand).
    lenient_arrows -- if True, accept a stray rightward arrow (e.g. ``➡``, ``=>``) used as an
        edge connector, warn, and continue. Default False raises ``EdgeArrowError``.

    Returns: ``ParseResult(doc_iri, graph, nodes_added)``
    '''
    text = fp if isinstance(fp, str) else fp.read()
    parser = LiterateParser(
        document_source_assertions=document_source_assertions,
        encoding=encoding,
        lenient_arrows=lenient_arrows,
    )
    return parser.parse(text, g, encoding=encoding, merge=merge)
