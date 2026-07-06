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
from onya.serial._literate_parse import (
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
        return f'"{s}"'
    return s


def _write_assertions(node, out, indent: str, nodebase, prefixes, bracket_curie: bool):
    for prop in sorted(node.properties, key=lambda p: str(p.label)):
        label = _format_label(prop.label, prefixes, bracket_curie=bracket_curie)
        out.write(f'{indent}* {label}: {_format_value(prop.value, nodebase, prefixes)}\n')
        if prop.id is not None:
            out.write(f'{indent}    * @id: {shorten_node_id(prop.id, nodebase)}\n')
        for nested in sorted(prop.properties, key=lambda p: str(p.label)):
            nested_label = _format_label(nested.label, prefixes, bracket_curie=bracket_curie)
            out.write(
                f'{indent}    * {nested_label}: '
                f'{_format_value(nested.value, nodebase, prefixes)}\n'
            )

    for edge in sorted(node.edges, key=lambda e: str(e.label)):
        label = _format_label(edge.label, prefixes, bracket_curie=bracket_curie)
        target = shorten_node_id(edge.target.id, nodebase)
        out.write(f'{indent}* {label} -> {target}\n')
        if edge.id is not None:
            out.write(f'{indent}    * @id: {shorten_node_id(edge.id, nodebase)}\n')
        for nested in sorted(edge.properties, key=lambda p: str(p.label)):
            nested_label = _format_label(nested.label, prefixes, bracket_curie=bracket_curie)
            out.write(
                f'{indent}    * {nested_label}: '
                f'{_format_value(nested.value, nodebase, prefixes)}\n'
            )


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
            doc_node = model.nodes[document_s]
            for prop in sorted(doc_node.properties, key=lambda p: str(p.label)):
                key = _format_label(prop.label, all_prefixes, bracket_curie=bracket_curie)
                out.write(
                    f'* {key}: {_format_value(prop.value, nodebase, all_prefixes)}\n'
                )
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
        _write_assertions(node, out, '', nodebase, all_prefixes, bracket_curie)
        out.write('\n')
    return


def read(fp, g=None, *, document_source_assertions: bool = False, encoding: str = 'utf-8'):
    '''
    Read Onya Literate format from a file-like object (or text string) into a graph.

    fp -- file-like object with a ``.read()`` method, OR a ``str`` of Onya Literate source
    g -- graph to populate; if None, a new ``onya.graph.graph`` is created
    document_source_assertions -- if True, tag each created assertion with an @source sub-property
    encoding -- character encoding hint passed through to the parser

    Returns: ``ParseResult(doc_iri, graph, nodes_added)``
    '''
    text = fp if isinstance(fp, str) else fp.read()
    parser = LiterateParser(
        document_source_assertions=document_source_assertions,
        encoding=encoding,
    )
    return parser.parse(text, g, encoding=encoding)
