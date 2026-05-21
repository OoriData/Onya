# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.util
from amara import iri

from onya import ONYA_BASEIRI

__all__ = [
    'abbreviate',
    'namespace_for_curie',
    'join_namespace',
    'curie_local_for_iri',
    'compact_iri',
]


def abbreviate(rel, bases):
    '''Abbreviate an IRI using base IRIs for more readable labels'''
    for base in bases:
        abbr = iri.relativize(rel, base, subPathOnly=True)
        if abbr:
            if base is ONYA_BASEIRI:
                abbr = '@' + abbr
            return abbr
    return str(rel)


def namespace_for_curie(base: str) -> str:
    '''
    Canonical namespace base for CURIE join/split (strip trailing ``/`` unless ``#``-delimited).
    '''
    if not base:
        return base
    if base.endswith('#'):
        return base
    return base.rstrip('/')


def join_namespace(namespace: str, local: str) -> str:
    '''
    Join a namespace base with a CURIE local name (RDF/XML-style).

    Avoids a duplicate slash when the base already ends with ``/``.
    '''
    if not local:
        return namespace
    if local[0] in '#?':
        return namespace + local
    if local[0] == '/':
        return namespace.rstrip('/') + local
    if namespace.endswith(('#', '/', '?')):
        return namespace + local
    return f'{namespace}/{local}'


def curie_local_for_iri(full: str, namespace: str) -> str | None:
    '''
    If ``full`` is in ``namespace``, return the local name; otherwise ``None``.
    '''
    full = str(full)
    ns = namespace_for_curie(namespace)
    if full == ns:
        return ''
    if ns.endswith('#'):
        if full.startswith(ns):
            return full[len(ns):]
        return None
    prefix = ns if ns.endswith('/') else f'{ns}/'
    if full.startswith(prefix):
        return full[len(prefix):]
    return None


def compact_iri(
    full: str,
    prefixes: dict[str, str] | None,
    *,
    default_bare_prefix: str | None = 'schema',
    bracket: bool = False,
) -> str:
    '''
    Render a full IRI as a compact CURIE or bare local name.

    Longest matching prefix wins. When the match is ``default_bare_prefix``, return
    only the local part (e.g. ``name``). Otherwise return ``prefix:local``.
    If ``bracket`` is True, wrap the result in ``<…>`` (for explicit IRI form).
    If no prefix matches, return ``<full-iri>``.
    '''
    full = str(full)
    if not prefixes:
        return f'<{full}>' if bracket else f'<{full}>'

    best_prefix: str | None = None
    best_local: str | None = None
    best_ns_len = -1

    for prefix_name, ns in sorted(
        prefixes.items(),
        key=lambda item: len(namespace_for_curie(item[1])),
        reverse=True,
    ):
        local = curie_local_for_iri(full, ns)
        if local is None:
            continue
        ns_len = len(namespace_for_curie(ns))
        if ns_len > best_ns_len:
            best_prefix = prefix_name
            best_local = local
            best_ns_len = ns_len

    if best_prefix is None:
        return f'<{full}>'

    if best_prefix == default_bare_prefix and best_local:
        rendered = best_local
    elif best_local == '':
        rendered = f'{best_prefix}:'
    else:
        rendered = f'{best_prefix}:{best_local}'

    if bracket:
        return f'<{rendered}>'
    return rendered
