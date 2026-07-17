# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial._literate_parse
'''
Internal implementation of the Onya Literate parser.

Public API is exposed via ``onya.serial.literate`` (``LiterateParser``, ``read``, ``write``,
``ParseResult``, ``SchemaPrefixConflict``). Import from there, not from this module.

Onya Literate, or Onya Lit, is a Markdown-based format.

see: the [Onya Literate format documentation](https://github.com/OoriData/Onya/blob/main/SPEC.md#onya-literate-serialization)
'''

import re
import warnings
from dataclasses import dataclass
from enum import Enum

from amara import iri  # for absolutize & matches_uri_syntax

from onya import I, ONYA_BASEIRI, ONYA_NULL, LITERAL
from onya.graph import AssertionIdConflict, edge as edge_cls
from onya.terms import ONYA_DOCUMENT, ONYA_SOURCE_REL, ONYA_INTERP, RESERVED_INTERP_NAMES, INTERP_NONE
from onya.util import join_namespace, namespace_for_curie

from pyparsing import (
    ParserElement, Literal, html_comment, Optional, Word, alphas, alphanums,
    Combine, MatchFirst, QuotedString, Regex, ZeroOrMore, White, Suppress,
    Group, DelimitedList, Forward, OneOrMore, rest_of_line, ParseBaseException
)  # pip install pyparsing
ParserElement.set_default_whitespace_chars(' \t')

URI_EXPLICIT_PAT = re.compile('<(.+)>', re.DOTALL)
# Compact CURIE: prefix:localName (prefix is a QName NCName; not an absolute IRI scheme)
CURIE_PAT = re.compile(r'^([A-Za-z][\w.\-]*):([^:]+)$')
# A node header `[…]` holds a set of types, whitespace-separated. `<…>` wrappers
# (explicit IRIs/CURIEs) are kept whole even if they contain whitespace.
TYPE_REF_PAT = re.compile(r'<[^>]*>|\S+')

SOURCE_REL = ONYA_SOURCE_REL


class value_type(Enum):
    '''
    Basic typing info for values (really just text vs node reference)
    '''
    TEXT_VAL = 1
    RES_VAL = 2
    UNKNOWN_VAL = 3


# For parse trees
@dataclass
class prop_info:
    indent: int = None      # 
    key: str = None         # 
    value: list = None      # 
    children: list = None   # 
    is_text_ref: bool = False  # True if this is a text reference (uses ::)
    is_edge: bool = False   # True if this is an edge (uses ->)
    multiline_text: str = None  # For storing multiline text content


@dataclass
class doc_info:
    iri: str = None         # iri of the doc being parsed, itself
    nodebase: str = None    # used to resolve relative node IRIs
    schemabase: str = None  # used to resolve relative schema IRIs
    typebase: str = None    # used to resolve relative type IRIs 
    lang: str = None        # other IRI abbreviations
    iris: dict = None       # iterpretations of untyped values (e.g. string vs list of strs vs IRI)
    text_refs: dict = None  # text references defined with :name = """content"""
    pending_edges: list = None  # deferred (edge, target_id) links resolved after all @ids are known
    interp_defaults: dict = None  # docheader @interpretations: resolved label IRI -> interp IRI/_CANCEL
    interp_defaults_raw: list = None  # raw (label_str, interp_raw) pairs, resolved after header parse


class SchemaPrefixConflict(ValueError):
    '''Raised when ``schema:`` under ``@iri`` disagrees with top-level ``@schema``.'''


class InterpretationParseError(ValueError):
    '''
    Raised for `@as` / `@interpretations` authoring errors: a second `@as` on one
    property, or a repeated label within an `@interpretations` stanza. An *unknown*
    interpretation name is never an error — the IRI is recorded and travels with the data
    (see SPEC: @as).
    '''


class LiterateParseError(ValueError):
    '''
    Base for *friendly* Onya Literate parse diagnostics: a structural failure translated into
    an actionable message (which construct is at fault, and how to fix it) instead of
    pyparsing's raw ``Expected end of text`` / grammar dump. Subclasses `ValueError`, so
    existing ``except ValueError`` handlers keep working. See `EdgeArrowError` and
    `LiterateSyntaxError`.
    '''


class EdgeArrowError(LiterateParseError):
    '''
    Raised (in the default strict mode) when a list item uses a rightward arrow that is
    *not* a valid Onya edge connector — e.g. ``➡`` (U+27A1) or an ASCII ``=>`` where ``->``
    or ``→`` (U+2192) was meant. The message names the offending character and shows the
    corrected line for easy cut & paste. `LiterateParser(lenient_arrows=True)` accepts the
    stray arrow, warns, and parses on. See `BAD_EDGE_ARROWS`.
    '''


class LiterateSyntaxError(LiterateParseError):
    '''
    A structural parse failure rendered as an actionable message. It names the construct at
    fault — node header, node identifier, `[Type]` bracket, assertion, code fence, preamble
    prose — and, where it can, suggests the fix (e.g. `Capt. Doran` → `CaptDoran`). Falls
    back to a generic-but-clean message that still says what the parser expected, never the
    raw grammar dump. Like `EdgeArrowError` it is gated on an *actual* parse failure, so it
    never fires on valid input. Carries `lineno`, `line`, and a `category` slug for callers.
    '''
    def __init__(self, message, *, lineno=None, line=None, category=None):
        super().__init__(message)
        self.lineno = lineno
        self.line = line
        self.category = category


# Sentinel for the reserved bare name `none`: it names no interpretation. Its only role is
# to cancel a docheader default on one property (precedence: inline `@as` > docheader >
# nothing); it is never stored, so a property resolving to `_CANCEL` keeps `interp` unset.
class _Cancel:
    def __repr__(self):
        return '<interp none>'


_CANCEL = _Cancel()


def _resolve_interp(raw, doc: 'doc_info'):
    '''
    Resolve an interpretation name (the RHS of `@as` or an `@interpretations` line) to an
    IRI, or to `_CANCEL` for the bare name `none`. Reserved bare names resolve into the
    Onya interpretation vocabulary; everything else resolves through the document's IRI
    machinery (absolute IRIs pass through, `@iri` abbreviations apply). An unknown name is
    not an error — the IRI is recorded regardless.
    '''
    name = str(raw).strip()
    if name == INTERP_NONE:
        return _CANCEL
    if name in RESERVED_INTERP_NAMES:
        return ONYA_INTERP(name)
    # Non-reserved: an IRI reference. base=None so absolute IRIs and CURIEs pass through
    # without being joined to a node/schema base (an interpretation is not a schema label).
    return expand_iri(name, None, doc=doc)


def _resolve_interp_defaults(doc: 'doc_info') -> None:
    '''
    Resolve a docheader `@interpretations` stanza's raw (label, interp-name) pairs into
    `doc.interp_defaults` (resolved label IRI -> interp IRI or `_CANCEL`). Labels resolve
    against `@schema` exactly as assertion labels do; interp names resolve as `@as` does.
    A repeated resolved label within the stanza is a parse error.
    '''
    if not doc.interp_defaults_raw:
        return
    doc.interp_defaults = {}
    for label_raw, interp_raw in doc.interp_defaults_raw:
        label_iri = expand_iri(label_raw, doc.schemabase, doc=doc)
        if label_iri in doc.interp_defaults:
            raise InterpretationParseError(
                f'Duplicate label {str(label_iri)!r} in @interpretations stanza'
            )
        doc.interp_defaults[label_iri] = _resolve_interp(interp_raw, doc)


class NamespaceBaseError(ValueError):
    '''Raised when a bare-name base (``@nodebase``/``@schema``/``@typebase``) lacks a
    trailing separator (``/``, ``#``, or ``?``) and would mint mashed IRIs.'''


# Bare node ids / labels / types concatenate onto these bases (see ``_lexical_join``),
# so a base must end in one of these or base and local name silently mash together.
_NAMESPACE_BASE_TERMINATORS = ('/', '#', '?')


def _check_namespace_bases(doc: doc_info, *, strict: bool) -> None:
    '''
    Validate the document's bare-name bases end in a separator.

    Unlike ``@iri`` CURIE prefixes (which get RDF/XML separator insertion via
    ``join_namespace``), ``@nodebase`` / ``@schema`` / ``@typebase`` join bare node
    ids, labels, and types by pure concatenation (``_lexical_join``). A base lacking a
    trailing ``/``, ``#``, or ``?`` therefore mints mashed IRIs — e.g.
    ``@nodebase https://ex.org/g`` + ``Node`` -> ``https://ex.org/gNode``.

    During the deprecation window (``strict=False``) this emits a ``DeprecationWarning``;
    once ``strict`` is set it raises ``NamespaceBaseError``. Only explicitly-declared
    bases are checked — the ``@nodebase`` -> ``@document`` fallback is out of scope, since
    ``@document`` is an identity IRI that conventionally carries no trailing separator.
    '''
    for name, base in (('@nodebase', doc.nodebase),
                       ('@schema', doc.schemabase),
                       ('@typebase', doc.typebase)):
        if not base or base.endswith(_NAMESPACE_BASE_TERMINATORS):
            continue
        msg = (
            f'{name} base {base!r} does not end in a separator (`/`, `#`, or `?`). '
            f'Onya joins bare node ids, labels, and types to this base by concatenation, '
            f'so it will mint mashed IRIs such as {base + "Local"!r}. Add a trailing `/` '
            f'(or `#`/`?`).'
        )
        if strict:
            raise NamespaceBaseError(msg)
        warnings.warn(
            msg + ' This will raise NamespaceBaseError in a future Onya release.',
            DeprecationWarning, stacklevel=2,
        )


def _register_iri_prefix(doc: doc_info, prefix: str, uri: str | None) -> None:
    if uri is None:
        return
    if doc.iris is None:
        doc.iris = {}
    uri_norm = uri if uri.endswith('#') else namespace_for_curie(uri)
    if prefix == 'schema':
        if doc.schemabase:
            expected = namespace_for_curie(doc.schemabase)
            if uri_norm != expected:
                raise SchemaPrefixConflict(
                    f'@iri prefix `schema` ({uri!r}) does not match @schema ({doc.schemabase!r}); '
                    f'after normalization: {uri_norm!r} vs {expected!r}'
                )
        doc.iris['schema'] = uri_norm
    else:
        doc.iris[prefix] = uri_norm


def _sync_schema_prefix(doc: doc_info) -> None:
    '''Register ``schema`` in ``doc.iris`` from ``@schema``; raise if ``@iri`` disagrees.'''
    if not doc.schemabase:
        return
    if doc.iris is None:
        doc.iris = {}
    canonical = namespace_for_curie(doc.schemabase)
    if 'schema' in doc.iris and doc.iris['schema'] != canonical:
        raise SchemaPrefixConflict(
            f'@iri prefix `schema` ({doc.iris["schema"]!r}) does not match '
            f'@schema ({doc.schemabase!r}); after normalization: '
            f'{doc.iris["schema"]!r} vs {canonical!r}'
        )
    doc.iris['schema'] = canonical


@dataclass
class value_info:
    verbatim: int = None    # Literal value input text
    typeindic: int = None   # Value type indicator (from value_type enum)

@dataclass
class ParseResult:
    '''
    Result of parsing an Onya Literate document.
    '''
    doc_iri: str | None
    graph: object
    nodes_added: set


class LiterateParser:
    '''
    Onya Literate parser with configurable behavior.

    The classic `parse()` function remains available for backwards compatibility,
    but new behavior flags are supported via this class.
    '''
    def __init__(self, *, document_source_assertions: bool = False, encoding: str = 'utf-8',
                 strict_namespace_bases: bool = False,
                 warn_implicit_doc_ids: bool = False,
                 warn_empty_blocks: bool = True,
                 lenient_arrows: bool = False):
        '''
        document_source_assertions -- if set, add @source sub-properties on created assertions,
            including nested assertions but excluding document header declarations
        encoding -- character encoding used in processing the input text (defaults to UTF-8)
        strict_namespace_bases -- if set, raise NamespaceBaseError when an explicit
            @nodebase/@schema/@typebase lacks a trailing separator (`/`, `#`, or `?`).
            Defaults to False during the deprecation window, which warns instead; a
            future Onya release will flip this default to True.
        warn_implicit_doc_ids -- if set, emit a warning each time a
            relative node id is resolved off @document (the @nodebase fallback) using an
            implicit `#` separator. Off by default: that resolution is a silent
            serialization rule. See `_resolve_node_id`.
        warn_empty_blocks -- if set (default), warn when a node block has neither a type
            nor any assertions: such a block contributes nothing to the model beyond
            ensuring its node id exists. On by default since an empty block is usually an
            authoring or round-trip artifact; pass False to silence.
        lenient_arrows -- controls handling of a stray rightward arrow used where an edge
            connector was meant (e.g. `* knows ➡ B`, or ASCII `=>` / `-->`). Default False:
            such a line raises `EdgeArrowError`, naming the character and showing the
            corrected line. If set, the stray arrow is accepted as an edge, a warning is
            emitted, and parsing continues. Valid edge arrows remain only `->` and `→`.
        '''
        self.document_source_assertions = document_source_assertions
        self.encoding = encoding
        self.strict_namespace_bases = strict_namespace_bases
        self.warn_implicit_doc_ids = warn_implicit_doc_ids
        self.warn_empty_blocks = warn_empty_blocks
        self.lenient_arrows = lenient_arrows

    def parse(self, lit_text, graph_obj=None, *, encoding: str | None = None,
              merge: bool = False) -> ParseResult:
        '''
        Parse Onya Literate source text

        - If `graph_obj` is provided, assertions are added to it. Parsing does not merge:
          overlapping assertions accumulate as distinct occurrences until the caller
          explicitly invokes `graph_obj.merge()`.
        - If `graph_obj` is None, a new `onya.graph.graph` is created
        - `merge` -- convenience: when True, call `graph_obj.merge()` once after parsing
          (collapsing duplicate assertions per the SPEC identity rules). Defaults to False,
          preserving the on-demand, never-ambient default; it is purely a one-call
          shorthand for the common parse-then-merge workflow.

        Returns: `ParseResult(doc_iri, graph, nodes_added)`
        '''
        if graph_obj is None:
            # Lazy import to avoid circular dependency concerns
            from onya.graph import graph as graph_cls
            graph_obj = graph_cls()

        nodes_before = set(getattr(graph_obj, 'nodes', {}).keys()) if hasattr(graph_obj, 'nodes') else set(graph_obj)

        doc = doc_info()
        doc.iris = {}  # Initialize the iris dictionary
        doc.text_refs = {}  # Initialize the text references dictionary
        doc.pending_edges = []  # Edge targets are resolved after all @id declarations are seen

        parsed = self._parse_string(lit_text)

        # First pass: collect all text reference definitions
        for item in parsed:
            if isinstance(item, tuple) and item[0] == 'text_ref_def':
                ref_name, ref_content = item[1], item[2]
                doc.text_refs[ref_name] = str(ref_content)

        # Second pass: process node blocks (edge targets are deferred, not resolved yet)
        for item in parsed:
            if not (isinstance(item, tuple) and item[0] == 'text_ref_def'):
                process_nodeblock(item, graph_obj, doc, self)

        # Third pass: resolve deferred edge targets now that every @id is known. A target
        # id matching a registered assertion @id links to that assertion; otherwise it is a
        # node id (an existing node, else a freshly-minted one).
        _resolve_pending_edges(graph_obj, doc)

        # Parse-time collision: an @id shares the node id space, so it must not equal any node id.
        assertion_ids = getattr(graph_obj, 'assertion_ids', {})
        node_ids = getattr(graph_obj, 'nodes', {})
        collisions = set(assertion_ids) & set(node_ids)
        if collisions:
            raise AssertionIdConflict(
                f'Assertion id(s) collide with node id(s): {sorted(map(str, collisions))}'
            )

        # Parsing does NOT merge by default: duplicate/overlapping assertions accumulate as
        # distinct occurrences until a consumer calls `graph.merge()` — merge is on-demand,
        # never ambient (consistent with the interpretation layer). The `merge` flag is an
        # opt-in shorthand for the common parse-then-merge workflow, nothing more.
        if merge:
            graph_obj.merge()

        nodes_after = set(getattr(graph_obj, 'nodes', {}).keys()) if hasattr(graph_obj, 'nodes') else set(graph_obj)
        nodes_added = nodes_after - nodes_before

        return ParseResult(doc.iri, graph_obj, nodes_added)

    def _parse_string(self, lit_text):
        '''
        Run the grammar, converting a stray-edge-arrow failure into either a friendly
        `EdgeArrowError` (default) or a warn-and-continue reparse (`lenient_arrows`).

        A wrong rightward arrow (`➡`, `=>`, ...) always makes pyparsing fail, and it reports
        the offending list item as the failing line (`exc.line`) — so we only look for a bad
        arrow *there*, gated on an actual failure. That means arrows sitting harmlessly inside
        a property value never trigger this (those lines parse fine), and any failure whose
        line holds no known bad arrow is handed to `_diagnose_syntax` for a friendly message.
        '''
        text = lit_text
        # Bound the lenient reparse loop: each pass fixes one line, so line-count+1 is ample.
        for _ in range(text.count('\n') + 2):
            try:
                return node_seq.parse_string(text, parse_all=True)
            except ParseBaseException as exc:
                match = _BAD_ARROW_RE.search(exc.line or '')
                if match is None:
                    # Not an arrow slip — translate the raw failure into an actionable message.
                    raise _diagnose_syntax(exc) from exc
                arrow = match.group(0)
                corrected = _BAD_ARROW_RE.sub('->', exc.line)
                if not self.lenient_arrows:
                    raise EdgeArrowError(
                        f'line {exc.lineno}: {_describe_bad_arrow(arrow)} is not a valid Onya '
                        f"edge arrow. Use '->' or '→' (U+2192) instead. Corrected line:\n"
                        f'    {corrected.strip()}'
                    ) from exc
                # Lenient: warn, rewrite every bad arrow on the failing line, and reparse.
                warnings.warn(
                    f'line {exc.lineno}: {_describe_bad_arrow(arrow)} used as an edge arrow; '
                    "treating it as '->'. Prefer '->' or '→' (U+2192).",
                    stacklevel=3,
                )
                lines = text.split('\n')
                lines[exc.lineno - 1] = _BAD_ARROW_RE.sub('->', lines[exc.lineno - 1])
                text = '\n'.join(lines)
        # Reached only if lenient rewrites never converge; surface a friendly diagnostic.
        try:
            return node_seq.parse_string(text, parse_all=True)
        except ParseBaseException as exc:
            raise _diagnose_syntax(exc) from exc

    def _node_base(self, doc: doc_info) -> str | None:
        '''
        Base used for resolving relative node IDs. Defaults to @document if
        @nodebase is not specified.
        '''
        return doc.nodebase or doc.iri

    def _type_base(self, doc: doc_info) -> str | None:
        '''
        Base used for resolving relative type IRIs. Defaults to @schema if
        @typebase is not specified.

        @typebase is for less common cases where types need a different base IRI
        than properties. In most cases, @schema alone suffices for both properties
        and types.
        '''
        return doc.typebase or doc.schemabase

    def _maybe_add_source(self, assertion_obj, doc: doc_info):
        '''
        Optionally add @source sub-property to assertions for provenance.
        '''
        if not self.document_source_assertions:
            return
        if not doc.iri:
            return
        # Properties are string-valued in core Onya; store source IRI as string.
        assertion_obj.add_property(SOURCE_REL, doc.iri)


def _make_tree(string, location, tokens):
    '''
    Parse action to return a parsed tree node from tokens
    '''
    return prop_info(indent=len(tokens[0]), key=tokens[1],
                        value=tokens[2], children=None)


def _make_edge_tree(string, location, tokens):
    '''
    Parse action to return a parsed tree node for edges (->)
    '''
    return prop_info(indent=len(tokens[0]), key=tokens[1],
                        value=tokens[2], children=None, is_edge=True)


def _make_value(string, location, tokens):
    '''
    Parse action to make sure the right type of value is created during parse
    '''
    val = tokens[0]
    # Must check IRI first, since it is a subclass of str
    if isinstance(val, I):
        typeindic = value_type.RES_VAL
    elif isinstance(val, LITERAL):
        typeindic = value_type.TEXT_VAL
    elif isinstance(val, str):
        val = val.strip()
        typeindic = value_type.UNKNOWN_VAL

    return value_info(verbatim=val, typeindic=typeindic)


def literal_parse_action(toks):
    '''
    Parse action to coerce to literal value
    '''
    return LITERAL(toks[0])


def iriref_parse_action(toks):
    '''
    Parse action to coerce to IRI reference value
    '''
    return I(toks[0])

RIGHT_ARROW     = Literal('->') | Literal('→')  # U+2192
DOUBLE_COLON    = Literal('::')  # For text references

# Rightward arrows commonly typed by mistake in place of the edge connector. The only valid
# edge arrows are ASCII `->` and `→` (U+2192); anything here is a near-miss we can name back
# to the author. Keyed by the literal token → (human name, codepoint label or None for ASCII).
BAD_EDGE_ARROWS = {
    '➡': ('Black Rightwards Arrow', 'U+27A1'),
    '⟶': ('Long Rightwards Arrow', 'U+27F6'),
    '↦': ('Rightwards Arrow from Bar', 'U+21A6'),
    '⇨': ('Rightwards White Arrow', 'U+21E8'),
    '➔': ('Heavy Wide-Headed Rightwards Arrow', 'U+2794'),
    '➜': ('Heavy Round-Tipped Rightwards Arrow', 'U+279C'),
    '➝': ('Heavy Rightwards Arrow', 'U+279D'),
    '⇒': ('Rightwards Double Arrow', 'U+21D2'),
    '⟹': ('Long Rightwards Double Arrow', 'U+27F9'),
    '⇢': ('Rightwards Dashed Arrow', 'U+21E2'),
    '⭢': ('Rightwards Arrow', 'U+2B62'),
    '=>': ('ASCII fat arrow', None),
    '-->': ('ASCII long arrow', None),
}
# Longest tokens first so `-->` wins over any `->`-like prefix scan (matters for the sub()).
_BAD_ARROW_RE = re.compile('|'.join(re.escape(a) for a in sorted(BAD_EDGE_ARROWS, key=len, reverse=True)))


def _describe_bad_arrow(arrow: str) -> str:
    '''Render an offending arrow as ``'➡' (U+27A1 Black Rightwards Arrow)`` for a message.'''
    name, codepoint = BAD_EDGE_ARROWS[arrow]
    inner = f'{codepoint} {name}' if codepoint else name
    return f'{arrow!r} ({inner})'


def _diagnose_syntax(exc) -> LiterateSyntaxError:
    '''
    Translate a pyparsing failure into a `LiterateSyntaxError` with an actionable message.

    Keyed on the failing line (`exc.line`, which pyparsing reports as the first *unconsumed*
    line — reliably the actual offending line for the malformations LLMs produce). Recognizes
    the common slips (a spaced node id, an unclosed `[Type]`, a stray/malformed assertion, a
    Markdown code fence, preamble prose) and always returns a clean message — falling back to
    a generic one that still names what the parser expected, never the raw grammar dump. The
    original exception is chained via ``raise ... from exc`` at the call site.
    '''
    lineno = getattr(exc, 'lineno', None)
    raw = getattr(exc, 'line', '') or ''
    stripped = raw.strip()
    where = f'line {lineno}' if lineno else 'input'

    def err(msg, category):
        return LiterateSyntaxError(msg, lineno=lineno, line=raw, category=category)

    if not stripped:
        return err(f'{where}: unexpected end of input, or a blank where an Onya Literate block '
                   'was expected. A file must begin with a `# @docheader` block.', 'empty')

    # Markdown code fence wrapping the graph (a frequent LLM output artifact)
    if stripped.startswith('```') or stripped.startswith('~~~'):
        return err(f'{where}: found a Markdown code fence ({stripped[:8]!r}). Onya Literate *is* '
                   'Markdown — do not wrap it in a code fence; remove the opening and closing '
                   'fence lines.', 'code-fence')

    # Node header line: `# NodeID [Type ...]`
    if stripped.startswith('#'):
        rest = stripped.lstrip('#').strip()
        if '[' in rest and ']' not in rest:
            id_guess = rest.split('[', 1)[0].strip() or 'NodeID'
            return err(f'{where}: node header is missing the closing `]` on its type list: '
                       f'`{stripped}`. Types go in brackets, e.g. `# {id_guess} [Person]`.',
                       'type-bracket')
        id_part = rest.split('[', 1)[0].strip()
        if id_part and any(c.isspace() for c in id_part):
            # Build a clean single-token suggestion: drop spaces and punctuation (incl. the
            # stylistically-odd `.`), keeping the slug chars `_`/`-`. `Capt. Doran` -> `CaptDoran`.
            suggestion = re.sub(r'[^A-Za-z0-9_-]', '', id_part) or 'NodeID'
            return err(f'{where}: a node identifier must be a single token with no spaces; got '
                       f'`{id_part}`. Use e.g. `{suggestion}` as the id (it resolves against '
                       '@nodebase) and put the human-readable name in a `* name:` property.',
                       'node-id-space')
        # Header shape not obviously wrong — fall through to the generic message below.

    # Assertion line: property / edge / text reference
    elif stripped.startswith('*'):
        return err(f'{where}: could not parse the assertion `{stripped}`. An assertion must be '
                   '`* label: value`, `* label -> Target`, or `* label:: textref`, and must sit '
                   'under a `# NodeID [Type]` header. Check for a missing `:` or `->`, or a stray '
                   'character in the label.', 'assertion')

    # Anything else at block position: preamble prose, junk, etc.
    return err(f'{where}: unexpected content: `{stripped[:60]}`. Expected a node header '
               '(`# NodeID [Type]`), an assertion (`* label: value`), a text reference '
               '(`:name = \"\"\"…\"\"\"`), or the `# @docheader` block. A file must begin with '
               '`# @docheader` — remove any preamble or explanatory prose.', 'unexpected')

COMMENT         = html_comment  # Using HTML-style comments for cleaner markdown compatibility
OPCOMMENT       = Optional(COMMENT)
IDENT           = Word(alphas, alphanums + '_' + '-')
IDENT_KEY       = Combine(Optional('@') + IDENT).leave_whitespace()
# Compact CURIE as assertion label (must precede IRIREF, which would stop at the first colon)
CURIE_LABEL     = Regex(r'[A-Za-z][\w.\-]*:[A-Za-z][\w.\-]*')
# EXPLICIT_IRI    = QuotedString('<', end_quote_char='>')
QUOTED_STRING   = MatchFirst((QuotedString('"', esc_char='\\'), QuotedString("'", esc_char='\\'))) \
                    .set_parse_action(literal_parse_action)
# Triple-quoted strings for text references - handle multiline properly. Store the *inner*
# content (delimiters stripped): the value is the text, not `"""text"""`. Keeping the
# delimiters was a latent bug that also made the value un-round-trippable (a serializer
# cannot re-emit a value that embeds its own delimiters).
TRIPLE_QUOTED_STRING = Regex(r'"""([^"]*(?:"[^"]*)*?)"""', re.DOTALL) \
                        .set_parse_action(lambda tokens: LITERAL(tokens[0][3:-3]))
# See: https://rdflib.readthedocs.io/en/stable/_modules/rdflib/plugins/sparql/parser.html
IRIREF          = Regex(r'[^<>"{}|^`\\\[\]%s]*' % ''.join(
                        '\\x%02X' % i for i in range(33)
                    )) \
                    .set_parse_action(iriref_parse_action)
#REST_OF_LINE = rest_of_line.leave_whitespace()

blank_to_eol    = ZeroOrMore(COMMENT) + White('\n')
explicit_iriref = Combine(Suppress('<') + IRIREF + Suppress('>')) \
                    .set_parse_action(iriref_parse_action)
ASSERTION_LABEL = MatchFirst((explicit_iriref, CURIE_LABEL, IDENT_KEY, IRIREF))

# Text reference definition: :name = '''content'''
text_ref_def    = Suppress(':') + IDENT + Suppress('=') + TRIPLE_QUOTED_STRING

value_expr      = ( explicit_iriref + Suppress(ZeroOrMore(COMMENT)) ) | ( QUOTED_STRING + Suppress(ZeroOrMore(COMMENT)) ) | rest_of_line  # noqa: E501
prop            = Optional(White(' \t').leave_whitespace(), '') + Suppress('*' + White()) + \
                    ASSERTION_LABEL + Suppress(':') + Optional(value_expr, None)
# Text reference property: label:: reference_name
prop_text_ref   = Optional(White(' \t').leave_whitespace(), '') + Suppress('*' + White()) + \
                    ASSERTION_LABEL + Suppress(DOUBLE_COLON) + Optional(IRIREF, None)
edge            = Optional(White(' \t').leave_whitespace(), '') + Suppress('*' + White()) + \
                    ASSERTION_LABEL + Suppress(RIGHT_ARROW) + Optional(value_expr, None)
# Optional so an assertion-less ("empty") node block parses; Group keeps propset present
# (as an empty result) for the fixed-arity unpack in process_nodeblock.
propset         = Group(Optional(DelimitedList(prop_text_ref | prop | edge | COMMENT, delim='\n')))
node_header = Word('#') + Optional(IRIREF, None) + Optional(QuotedString('[', end_quote_char=']'), None)
node_block  = Forward()
node_block  << Group(node_header + White('\n').suppress() + Suppress(ZeroOrMore(blank_to_eol)) + propset)

# Start symbol - allow text reference definitions anywhere
node_seq    = OneOrMore(
                    Suppress(ZeroOrMore(blank_to_eol)) + \
                        (node_block | text_ref_def) + Optional(White('\n')).suppress() + \
                            Suppress(ZeroOrMore(blank_to_eol))
                    )

def _make_text_ref_tree(string, location, tokens):
    '''
    Parse action to return a parsed tree node for text references
    '''
    return prop_info(indent=len(tokens[0]), key=tokens[1],
                        value=tokens[2] if len(tokens) > 2 else None, children=None,
                        is_text_ref=True)

def parse_multiline_text(lines, start_idx, current_indent):
    '''
    Parse multiline text that continues after a property definition.
    Returns (text_content, next_line_idx)
    '''
    if start_idx >= len(lines):
        return '', start_idx

    text_lines = []
    i = start_idx

    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Check if this line is indented enough to be part of the multiline text
        # Must be indented more than the current property level
        line_indent = len(line) - len(line.lstrip())
        if line_indent > current_indent:
            # This is a continuation line
            text_lines.append(line[current_indent:])  # Remove the base indentation
            i += 1
        else:
            # This line is not indented enough, stop parsing multiline text
            break

    return '\n'.join(text_lines), i

def _make_text_ref_def(string, location, tokens):
    '''
    Parse action for text reference definitions
    '''
    return ('text_ref_def', tokens[0], tokens[1])


prop.set_parse_action(_make_tree)
prop_text_ref.set_parse_action(_make_text_ref_tree)
edge.set_parse_action(_make_edge_tree)
text_ref_def.set_parse_action(_make_text_ref_def)
value_expr.set_parse_action(_make_value)


_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+\-.]*:')


def _lexical_join(base: str, ref: str) -> str:
    '''
    Onya's IRI resolution convention is intentionally lexical: for relative refs,
    resolve by concatenation of base + ref.
    '''
    if base is None:
        return ref
    if ref is None:
        return ref
    # If ref already looks like an absolute IRI (has a scheme), don't join.
    if _SCHEME_RE.match(ref):
        return ref
    return f'{base}{ref}'


def _expand_curie(iri_in: str, doc: doc_info | None) -> str | None:
    '''
    Expand ``prefix:local`` using prefixes from the document ``@iri`` block.
    Returns the full IRI string, or None if not a CURIE or prefix is unknown.
    '''
    if not (m := CURIE_PAT.match(iri_in)):
        return None
    prefix, local = m.group(1), m.group(2)
    if doc is None or not doc.iris or prefix not in doc.iris:
        return None
    return join_namespace(doc.iris[prefix], local)


def expand_iri(iri_in, base, nodecontext=None, doc=None):
    if iri_in is None:
        return ONYA_NULL

    # Explicit <…> — inner may be a CURIE or a relative/absolute IRI ref
    if iri_match := URI_EXPLICIT_PAT.match(iri_in):
        inner = iri_match.group(1)
        if expanded := _expand_curie(inner, doc):
            return I(expanded)
        return I(inner if base is None else _lexical_join(base, inner))

    # Compact CURIE (e.g. acme:Client) before Onya @-vocab and relative expansion
    if expanded := _expand_curie(iri_in, doc):
        return I(expanded)

    # Onya built-in @property names (e.g. @document, @source)
    if iri_in.startswith('@'):
        return ONYA_BASEIRI(iri_in[1:])

    # Relative to base
    if nodecontext and not(iri.matches_uri_ref_syntax(iri_in)):
        raise ValueError(f'Invalid IRI reference provided for node context {nodecontext}: `{iri_in}`')
    fulliri = iri_in if base is None else _lexical_join(base, iri_in)
    return I(fulliri)


def _resolve_node_id(ref, doc: doc_info, parser: LiterateParser | None):
    '''
    Resolve a node id or edge-target id (``ref``) against the node base.

    With an explicit ``@nodebase``, this is plain concatenation via ``expand_iri`` (the
    base is required to end in a separator — see ``_check_namespace_bases``). When
    ``@nodebase`` is omitted, ids resolve off ``@document``; if that document IRI lacks a
    trailing separator, Onya inserts a ``#`` as an implicit separator — a serialization
    rule that keeps the natural ``@document http://e.o/doc`` usable as a node base:
    ``http://e.o/doc`` + ``N`` -> ``http://e.o/doc#N``. Only *relative* refs are affected
    (absolute IRIs and CURIEs ignore the base). Silent unless the parser was built with
    ``warn_implicit_doc_ids``.
    '''
    node_base = parser._node_base(doc) if parser else doc.nodebase
    using_doc_fallback = not doc.nodebase and node_base is not None and node_base == doc.iri
    if using_doc_fallback and not node_base.endswith(_NAMESPACE_BASE_TERMINATORS):
        result = expand_iri(ref, node_base + '#', doc=doc)
        implicit_applied = str(result) == node_base + '#' + str(ref)  # ref was relative
        if implicit_applied and parser and parser.warn_implicit_doc_ids:
            warnings.warn(
                f'Relative node id {ref!r} resolved off @document with an implicit `#` '
                f'separator -> {str(result)!r}. Set @nodebase explicitly to control this.',
                stacklevel=2,
            )
        return result
    return expand_iri(ref, node_base, doc=doc)


def _resolve_pending_edges(graph_obj, doc: doc_info):
    '''
    Bind deferred edge targets. Edge targets are collected during the node-block pass with
    their target left as ``None`` (see ``process_nodeblock``) so that an edge referencing an
    assertion by its ``@id`` can be linked whether that ``@id`` is declared before or after the
    reference. An id matching a registered assertion ``@id`` links to that assertion; otherwise
    it is treated as a node id — an existing node when present, else a newly-created one (the
    forward-reference placeholder behavior edges have always had).
    '''
    for edge_obj, target_id in (doc.pending_edges or ()):
        if target_id in graph_obj.assertion_ids:
            edge_obj.target = graph_obj.assertion_ids[target_id]
        elif target_id in graph_obj:
            edge_obj.target = graph_obj[target_id]
        else:
            edge_obj.target = graph_obj.node(target_id)


def _create_assertion(parent, pi, assertion_label, doc, parser: LiterateParser | None):
    '''
    Create the property or edge described by ``pi`` on ``parent`` (a node or another
    assertion) and return it, or None when there is nothing to create. Edge targets are
    deferred (see ``_resolve_pending_edges``); ``@source`` provenance is applied if enabled.
    '''
    created = None
    if pi.is_text_ref:
        ref_name = str(pi.value) if pi.value else None
        # Unknown reference falls back to an empty string value (kept lenient rather than raising).
        str_val = doc.text_refs.get(ref_name, '') if ref_name else ''
        created = parent.add_property(assertion_label, str_val)
    elif pi.value is not None:
        val = pi.value.verbatim
        if pi.is_edge:
            # RHS may name a node or an identified assertion, possibly a forward reference.
            target_id = _resolve_node_id(str(val), doc, parser)
            created = parent.add_edge(assertion_label, None)
            doc.pending_edges.append((created, target_id))
        else:
            created = parent.add_property(assertion_label, str(val))
    if created is not None and parser:
        parser._maybe_add_source(created, doc)
    return created


def _build_assertions(node, props, graph_obj, doc, parser: LiterateParser | None = None) -> bool:
    '''
    Build assertions (properties, edges, their `@id` / `@as` directives, arbitrary nesting, and
    `@interpretations` desugaring) onto `node` from a flat, indent-encoded list of parsed bullets.

    Shared by ordinary node blocks and the document node (`@docheader`), so the document node is
    a first-class node at the Literate boundary: its non-directive bullets carry the same
    expressiveness as any other node's (see SPEC § Document Header). Returns True if any assertion
    was created (used for the empty-block warning on ordinary nodes).
    '''
    # Nesting is tracked with a stack of (indent, assertion) frames. Each assertion's origin is
    # the nearest enclosing frame with strictly smaller indent (the node itself when none). This
    # supports arbitrary nesting depth for properties, edges, and `@id` alike.
    stack = []
    saw_assertion = False
    seen_as = set()  # id(parent) of assertions that already took an inline @as (dup -> parse error)

    for pi in props:
        if isinstance(pi, str):
            # Just a comment. Skip.
            continue

        # Handle text reference definitions
        if isinstance(pi, tuple) and pi[0] == 'text_ref_def':
            ref_name, ref_content = pi[1], pi[2]
            doc.text_refs[ref_name] = str(ref_content)
            continue

        # Unwind frames at this indent or deeper: they are siblings/children, not the parent.
        while stack and stack[-1][0] >= pi.indent:
            stack.pop()
        parent = stack[-1][1] if stack else node

        # `@id` is a directive, not an assertion: it names its enclosing assertion (the current
        # parent) rather than creating a property on it. At the node's own level (no enclosing
        # assertion) there is nothing to name, so it is ignored.
        if pi.key == '@id':
            if stack:
                raw = pi.value.verbatim if pi.value else None
                if raw is not None:
                    assertion_id = _resolve_node_id(str(raw), doc, parser)
                    try:
                        graph_obj.register_assertion_id(assertion_id, parent)
                    except AssertionIdConflict as e:
                        # Within a single document, a repeated @id is rejected as an authoring
                        # error. This is a parser-surface constraint only: the graph *merge*
                        # model (SPEC § Identity and graph merge, Rule 1) instead treats two
                        # assertions bearing the same id as the same assertion.
                        raise AssertionIdConflict(
                            f'{e} (a repeated @id within one Onya Literate document is a '
                            f'parser-surface limitation, not the graph merge rule: under merge, '
                            f'same-id assertions are the same assertion)'
                        ) from e
            continue

        # `@as` is a directive, not an assertion: like `@id`, it annotates its enclosing
        # assertion (the current parent) rather than creating a property. It sets `interp`.
        if pi.key == '@as':
            if not stack:
                # No enclosing assertion to annotate (node's own level): nothing to do.
                continue
            if isinstance(parent, edge_cls):
                # An edge's value is a node, not a string, so there is nothing to interpret.
                # Ignored with a warning; the syntax position is reserved (see SPEC: @as).
                warnings.warn(
                    '@as nested directly under an edge is ignored: an edge target is a node, '
                    'not a string to interpret. The position is reserved for a future meaning.',
                    stacklevel=2,
                )
                continue
            if id(parent) in seen_as:
                raise InterpretationParseError(
                    'Duplicate @as on one property: a property has at most one interpretation'
                )
            seen_as.add(id(parent))
            raw = pi.value.verbatim if pi.value else None
            if raw is not None:
                resolved = _resolve_interp(raw, doc)
                # `none` cancels a docheader default; anything else sets the interp. Inline @as
                # has already run *after* any docheader default was applied at creation, so it
                # wins (precedence: inline @as > docheader > nothing).
                parent.interp = None if resolved is _CANCEL else resolved
            continue

        assertion_label = expand_iri(pi.key, doc.schemabase, doc=doc)
        created = _create_assertion(parent, pi, assertion_label, doc, parser)
        if created is not None:
            saw_assertion = True
            # Desugar a docheader @interpretations default onto this property (any depth). Edges
            # carry no interpretation; a `none` default (`_CANCEL`) leaves `interp` unset. A later
            # inline @as on this same property overrides (handled above).
            if not pi.is_edge and doc.interp_defaults:
                default = doc.interp_defaults.get(assertion_label)
                if default is not None and default is not _CANCEL:
                    created.interp = default
            stack.append((pi.indent, created))

    return saw_assertion


def process_nodeblock(nodeblock, graph_obj, doc, parser: LiterateParser | None = None):
    headermarks, nid, ntype, props = nodeblock

    if nid == '@docheader':
        process_docheader(props, graph_obj, doc, parser)
        return

    nid = _resolve_node_id(nid, doc, parser)

    # Get or create the node
    if nid not in graph_obj:
        n = graph_obj.node(nid)
    else:
        n = graph_obj[nid]

    # Add types if specified. A node may carry a *set* of types, written
    # whitespace-separated inside the header brackets (e.g. `[Organization lv:Client]`).
    if ntype:
        type_base = parser._type_base(doc) if parser else doc.typebase
        for type_ref in TYPE_REF_PAT.findall(ntype):
            type_iri = expand_iri(type_ref, type_base, doc=doc)
            n.types.add(type_iri)

    saw_assertion = _build_assertions(n, props, graph_obj, doc, parser)

    # No assertion and no type: the block ensures the node id exists but otherwise makes no change
    # to the model — usually an authoring slip or a round-trip artifact (write() emits a bare block
    # for a target-only node).
    if parser and parser.warn_empty_blocks and not saw_assertion and not ntype:
        warnings.warn(
            f'Onya Literate: node block {str(nid)!r} is empty (no type or assertions); it makes '
            f'no change to the constructed model beyond ensuring the node id exists.',
            stacklevel=2,
        )


def process_docheader(props, graph_obj, doc, parser: LiterateParser | None = None):
    # The `@docheader` block IS the document node's block. Two kinds of bullet live here:
    # built-in *directives* (`@document`, `@nodebase`, `@schema`, `@typebase`, `@language`, and
    # the `@iri:` / `@interpretations:` config stanzas), which set document fields and create no
    # assertion; and ordinary *assertions* on the document node, which get the same full treatment
    # as any node block (properties, edges, `@id`/`@as`, arbitrary nesting) via _build_assertions.
    # Only the document id/type stay directive-driven (`@document` + implicit onya:Document); see
    # SPEC § Document Header.
    outer_indent = -1
    directive_owner = None  # None | '@iri' | '@interpretations' | 'ASSERTION'
    assertion_props = []    # non-directive bullets (with their nested descendants) for the doc node
    for prop in props:
        if isinstance(prop, str):  # a comment: no graph meaning
            continue
        if isinstance(prop, tuple) and prop[0] == 'text_ref_def':
            assertion_props.append(prop)  # registered by the shared builder
            continue

        # First bullet fixes the outer indent; bullets at it are directives/assertions, deeper
        # ones are the nested content of the current outer bullet.
        if outer_indent == -1:
            outer_indent = prop.indent
        if prop.indent == outer_indent:
            key = prop.key
            if key == '@document':
                doc.iri = prop.value.verbatim if prop.value else None
                directive_owner = None
            elif key == '@language':
                doc.lang = prop.value.verbatim if prop.value else None
                directive_owner = None
            elif key == '@nodebase' or key == '@base':
                # @base is retained as a legacy alias, but @nodebase is preferred.
                doc.nodebase = prop.value.verbatim if prop.value else None
                directive_owner = None
            elif key == '@schema':
                doc.schemabase = prop.value.verbatim if prop.value else None
                directive_owner = None
            elif key == '@typebase':
                # @typebase for less common cases where types need a different base than @schema
                doc.typebase = prop.value.verbatim if prop.value else None
                directive_owner = None
            elif key == '@iri':
                # Prefix block only; nested lines supply mappings (not a document assertion).
                directive_owner = '@iri'
            elif key == '@interpretations':
                # Interpretation defaults block; nested lines supply label -> interp mappings.
                # Collected raw and resolved after the whole header is parsed (so @schema and
                # @iri prefixes are known regardless of stanza order), then desugared onto each
                # matching assertion's `interp` — the stanza itself is not part of the graph.
                if doc.interp_defaults_raw is None:
                    doc.interp_defaults_raw = []
                directive_owner = '@interpretations'
            else:
                # A genuine assertion on the document node; hand it (and its descendants) to the
                # shared builder below.
                assertion_props.append(prop)
                directive_owner = 'ASSERTION'
        else:
            # Nested line: belongs to the current outer bullet.
            if directive_owner == '@iri':
                k, uri = prop.key, prop.value.verbatim if prop.value else None
                if k == '@nodebase' or k == '@base':
                    doc.nodebase = uri
                elif k == '@schema':
                    doc.schemabase = uri
                    _sync_schema_prefix(doc)
                elif k == '@typebase':
                    doc.typebase = uri
                else:
                    _register_iri_prefix(doc, k, uri)
            elif directive_owner == '@interpretations':
                # Defer resolution: labels resolve against @schema, which may be declared
                # after this stanza. Keep raw (label, interp-name) pairs for now.
                if prop.value is not None:
                    if doc.interp_defaults_raw is None:
                        doc.interp_defaults_raw = []
                    doc.interp_defaults_raw.append((prop.key, prop.value.verbatim))
            elif directive_owner == 'ASSERTION':
                assertion_props.append(prop)  # a descendant of a document-node assertion
            # else: nested under a scalar directive (e.g. under @document) -> ignored

    _sync_schema_prefix(doc)
    _check_namespace_bases(doc, strict=bool(parser and parser.strict_namespace_bases))
    _resolve_interp_defaults(doc)

    # Build the document node's assertions with the same machinery as any node block, so `@as`,
    # `@id`, nested/reified assertions, and edges all round-trip.
    if doc.iri:
        if doc.iri not in graph_obj:
            doc_node = graph_obj.node(doc.iri)
        else:
            doc_node = graph_obj[doc.iri]
        doc_node.types.add(ONYA_DOCUMENT)  # implicit type for document nodes
        _build_assertions(doc_node, assertion_props, graph_obj, doc, parser)
    return
