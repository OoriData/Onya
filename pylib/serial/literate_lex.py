# -*- coding: utf-8 -*-
# onya.serial.literate_lex.py
'''
Main body of the Onya Literate parser

Onya Literate, or Onya Lit, is a Markdown-based format

Proper entry point of use is onya.serial.literate

see: doc/literate_format.md

'''

import re
from dataclasses import dataclass
from enum import Enum

from amara import iri  # for absolutize & matches_uri_syntax

from pyparsing import * # pip install pyparsing
ParserElement.setDefaultWhitespaceChars(' \t')

from onya import I, ONYA_BASEIRI, ONYA_NULL, LITERAL

URI_ABBR_PAT = re.compile('@([\\-_\\w]+)([#/@])(.+)', re.DOTALL)
URI_EXPLICIT_PAT = re.compile('<(.+)>', re.DOTALL)

TYPE_REL = ONYA_BASEIRI('type')

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


@dataclass
class value_info:
    verbatim: int = None    # Literal value input text
    typeindic: int = None   # Value type indicator (from value_type enum)


def _make_tree(string, location, tokens):
    '''
    Parse action to return a parsed tree node from tokens
    '''
    return prop_info(indent=len(tokens[0]), key=tokens[1],
                        value=tokens[2], children=None)


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

COMMENT         = htmlComment  # Using HTML-style comments for cleaner markdown compatibility
OPCOMMENT       = Optional(COMMENT)
IDENT           = Word(alphas, alphanums + '_' + '-')
IDENT_KEY       = Combine(Optional('@') + IDENT).leaveWhitespace()
# EXPLICIT_IRI    = QuotedString('<', end_quote_char='>')
QUOTED_STRING   = MatchFirst((QuotedString('"', escChar='\\'), QuotedString("'", escChar='\\'))) \
                    .setParseAction(literal_parse_action)
# Triple-quoted strings for text references - handle multiline properly
TRIPLE_QUOTED_STRING = Regex(r'"""([^"]*(?:"[^"]*)*?)"""', re.DOTALL) \
                        .setParseAction(lambda tokens: LITERAL(tokens[0]))
# See: https://rdflib.readthedocs.io/en/stable/_modules/rdflib/plugins/sparql/parser.html
IRIREF          = Regex(r'[^<>"{}|^`\\\[\]%s]*' % "".join(
                        "\\x%02X" % i for i in range(33)
                    )) \
                    .setParseAction(iriref_parse_action)
#REST_OF_LINE = rest_of_line.leave_whitespace()

blank_to_eol    = ZeroOrMore(COMMENT) + White('\n')
explicit_iriref = Combine(Suppress("<") + IRIREF + Suppress(">")) \
                    .setParseAction(iriref_parse_action)

# Text reference definition: :name = """content"""
text_ref_def    = Suppress(':') + IDENT + Suppress('=') + TRIPLE_QUOTED_STRING

value_expr      = ( explicit_iriref + Suppress(ZeroOrMore(COMMENT)) ) | ( QUOTED_STRING + Suppress(ZeroOrMore(COMMENT)) ) | rest_of_line
prop            = Optional(White(' \t').leaveWhitespace(), '') + Suppress('*' + White()) + \
                    ( explicit_iriref | IDENT_KEY | IRIREF ) + Suppress(':') + Optional(value_expr, None)
# Text reference property: label:: reference_name
prop_text_ref   = Optional(White(' \t').leaveWhitespace(), '') + Suppress('*' + White()) + \
                    ( explicit_iriref | IDENT_KEY | IRIREF ) + Suppress(DOUBLE_COLON) + Optional(IRIREF, None)
edge            = Optional(White(' \t').leaveWhitespace(), '') + Suppress('*' + White()) + \
                    ( explicit_iriref | IDENT_KEY | IRIREF ) + Suppress(RIGHT_ARROW) + Optional(value_expr, None)
propset         = Group(delimited_list(prop_text_ref | prop | edge | COMMENT, delim='\n'))
node_header = Word('#') + Optional(IRIREF, None) + Optional(QuotedString('[', end_quote_char=']'), None)
node_block  = Forward()
node_block  << Group(node_header + White('\n').suppress() + Suppress(ZeroOrMore(blank_to_eol)) + propset)

# Start symbol - allow text reference definitions anywhere
node_seq    = OneOrMore(
                    Suppress(ZeroOrMore(blank_to_eol)) + \
                        (node_block | text_ref_def) + White('\n').suppress() + \
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
    """
    Parse multiline text that continues after a property definition.
    Returns (text_content, next_line_idx)
    """
    if start_idx >= len(lines):
        return "", start_idx

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

prop.setParseAction(_make_tree)
prop_text_ref.setParseAction(_make_text_ref_tree)
edge.setParseAction(_make_tree)
text_ref_def.setParseAction(_make_text_ref_def)
value_expr.setParseAction(_make_value)


def parse(lit_text, graph_obj, encoding='utf-8'):
    """
    Translate Onya Literate text into Onya graph

    lit_text -- Onya Literate source text
    graph_obj -- Onya graph to populate
    encoding -- character encoding (defaults to UTF-8)

    Returns: The document IRI from @document header, or None

    >>> from onya.driver.memory import newmodel
    >>> from onya.serial.literate import parse # Delegates to literate_lex.parse
    >>> m = newmodel()
    >>> parse(open('test/resource/poetry.onya').read(), m)
    'http://uche.ogbuji.net/poems/'
    >>> m.size()
    40
    >>> next(m.match(None, 'http://uche.ogbuji.net/poems/updated', '2013-10-15'))
    (I(http://uche.ogbuji.net/poems/1), I(http://uche.ogbuji.net/poems/updated), '2013-10-15', {})
    """
    # Set up document parameters
    doc = doc_info()
    doc.iris = {}  # Initialize the iris dictionary
    doc.text_refs = {}  # Initialize the text references dictionary

    parsed = node_seq.parseString(lit_text, parseAll=True)

    # First pass: collect all text reference definitions
    for item in parsed:
        if isinstance(item, tuple) and item[0] == 'text_ref_def':
            ref_name, ref_content = item[1], item[2]
            doc.text_refs[ref_name] = str(ref_content)

    # Second pass: process node blocks
    for item in parsed:
        if not (isinstance(item, tuple) and item[0] == 'text_ref_def'):
            # Handle node blocks
            process_nodeblock(item, graph_obj, doc)

    return doc.iri


def expand_iri(iri_in, base, nodecontext=None):
    if iri_in is None:
        return ONYA_NULL
    # Abreviation for special, Onya-specific properties
    if iri_in.startswith('@'):
        return I(iri.absolutize(iri_in[1:], ONYA_BASEIRI))

    # Is it an explicit IRI (i.e. with <…>)?
    if iri_match := URI_EXPLICIT_PAT.match(iri_in):
        return iri_match.group(1) if base is None else I(iri.absolutize(iri_match.group(1), base))

    # XXX Clarify this bit?
    if iri_match := URI_ABBR_PAT.match(iri_in):
        uri = iris[iri_match.group(1)]
        fulliri = URI_ABBR_PAT.sub(uri + '\\2\\3', iri_in)
    else:
        # Replace upstream ValueError with our own
        if nodecontext and not(iri.matches_uri_ref_syntax(iri_in)):
            # FIXME: Replace with a Onya-specific error
            raise ValueError(f'Invalid IRI reference provided for node context {nodecontext}: "{iri_in}"')
        fulliri = iri_in if base is None else I(iri.absolutize(iri_in, base))
    return I(fulliri)


def process_nodeblock(nodeblock, graph_obj, doc):
    headermarks, nid, ntype, props = nodeblock
    headdepth = len(headermarks)

    if nid == '@docheader':
        process_docheader(props, graph_obj, doc)
        return

    nid = expand_iri(nid, doc.nodebase)

    # Get or create the node
    if nid not in graph_obj:
        n = graph_obj.node(nid)
    else:
        n = graph_obj[nid]

    # Add type if specified
    if ntype:
        type_iri = expand_iri(ntype, doc.typebase)
        n.types.add(type_iri)

    # Track current assertion for nested assertions
    outer_indent = -1
    current_assertion = None

    for prop_info in props:
        if isinstance(prop_info, str):
            # Just a comment. Skip.
            continue

        # Handle text reference definitions
        if isinstance(prop_info, tuple) and prop_info[0] == 'text_ref_def':
            ref_name, ref_content = prop_info[1], prop_info[2]
            doc.text_refs[ref_name] = str(ref_content)
            continue

        # First assertion encountered determines outer indent
        if outer_indent == -1:
            outer_indent = prop_info.indent

        # Expand the assertion label IRI
        assertion_label = expand_iri(prop_info.key, doc.schemabase)

        if prop_info.indent == outer_indent:
            # This is a top-level assertion
            if prop_info.is_text_ref:
                # Handle text reference
                ref_name = str(prop_info.value) if prop_info.value else None
                if ref_name and ref_name in doc.text_refs:
                    str_val = doc.text_refs[ref_name]
                    current_assertion = n.add_property(assertion_label, str_val)
                else:
                    # Text reference not found, skip or use empty string
                    current_assertion = n.add_property(assertion_label, "")
            elif prop_info.value:
                val, typeindic = prop_info.value.verbatim, prop_info.value.typeindic

                if typeindic == value_type.RES_VAL:
                    # This is an edge (node to node)
                    target_id = expand_iri(val, doc.typebase)
                    # Get or create Janelaet node
                    if target_id not in graph_obj:
                        target_node = graph_obj.node(target_id)
                    else:
                        target_node = graph_obj[target_id]
                    # Add edge and track it for nested assertions
                    current_assertion = n.add_edge(assertion_label, target_node)
                elif typeindic == value_type.TEXT_VAL or typeindic == value_type.UNKNOWN_VAL:
                    # This is a property (node to string value)
                    str_val = str(val)
                    current_assertion = n.add_property(assertion_label, str_val)

        else:
            # This is a nested assertion on current_assertion
            if current_assertion is None:
                continue  # Skip nested without a parent

            if prop_info.is_text_ref:
                # Handle nested text reference
                ref_name = str(prop_info.value) if prop_info.value else None
                if ref_name and ref_name in doc.text_refs:
                    str_val = doc.text_refs[ref_name]
                    current_assertion.add_property(assertion_label, str_val)
            elif prop_info.value:
                val, typeindic = prop_info.value.verbatim, prop_info.value.typeindic
                if typeindic == value_type.RES_VAL:
                    # Nested edge
                    target_id = expand_iri(val, doc.typebase)
                    if target_id not in graph_obj:
                        target_node = graph_obj.node(target_id)
                    else:
                        target_node = graph_obj[target_id]
                    current_assertion.add_edge(assertion_label, target_node)
                elif typeindic == value_type.TEXT_VAL or typeindic == value_type.UNKNOWN_VAL:
                    # Nested property
                    str_val = str(val)
                    current_assertion.add_property(assertion_label, str_val)


def process_docheader(props, graph_obj, doc):
    outer_indent = -1
    current_outer_prop = None
    for prop in props:
        # Skip comments
        if isinstance(prop, str):
            continue

        # @iri section is where key IRI prefixes can be set
        # First property encountered determines outer indent
        if outer_indent == -1:
            outer_indent = prop.indent
        if prop.indent == outer_indent:
            current_outer_prop = prop
            #Setting an IRI for this very document being parsed
            if prop.key == '@document':
                doc.iri = prop.value.verbatim if prop.value else None
            elif prop.key == '@language':
                doc.lang = prop.value.verbatim if prop.value else None
            elif prop.key == '@base':
                doc.nodebase = doc.typebase = prop.value.verbatim if prop.value else None
            elif prop.key == '@schema':
                doc.schemabase = prop.value.verbatim if prop.value else None
            elif prop.key == '@resource-type' or prop.key == '@type-base':
                doc.typebase = prop.value.verbatim if prop.value else None
            #If we have a document node to which to attach them, just attach all other properties
            elif doc.iri:
                # Create document node if needed
                if doc.iri not in graph_obj:
                    doc_node = graph_obj.node(doc.iri)
                else:
                    doc_node = graph_obj[doc.iri]

                fullprop = I(iri.absolutize(prop.key, doc.schemabase))
                if prop.value:
                    doc_node.add_property(fullprop, prop.value.verbatim)
        else:
            # Handle nested properties (attributes)
            if current_outer_prop and current_outer_prop.key == '@iri':
                k, uri = prop.key, prop.value.verbatim if prop.value else None
                if k == '@base':
                    doc.nodebase = doc.typebase = uri
                elif k == '@schema':
                    doc.schemabase = uri
                elif k == '@resource-type' or k == '@type-base':
                    doc.typebase = uri
                else:
                    doc.iris[k] = uri
    return


'''
def handle_resourceset(ltext, **kwargs):
    'Helper that converts sets of resources from a textual format such as Markdown, including absolutizing relative IRIs'
    fullprop=kwargs.get('fullprop')
    rid=kwargs.get('rid')
    base=kwargs.get('base', ONYA_BASEIRI)
    model=kwargs.get('model')
    iris = ltext.strip().split()
    for i in iris:
        model.add(rid, fullprop, I(iri.absolutize(i, base)))
    return None


PREP_METHODS = {
    ONYA_BASEIRI + 'text': lambda x, **kwargs: x,
    # '@text': lambda x, **kwargs: x,
    ONYA_BASEIRI + 'resource': lambda x, base=ONYA_BASEIRI, **kwargs: I(iri.absolutize(x, base)),
    ONYA_BASEIRI + 'resourceset': handle_resourceset,
}

    from onya.driver.memory import newmodel
    m = newmodel()
    parse(open('/tmp/poetry.md').read(), m)
    print(m.size())
    import pprint; pprint.pprint(list(m.match()))
    # next(m.match(None, 'http://uche.ogbuji.net/poems/updated', '2013-10-15'))
'''

'''

for s in [  ' "quick-brown-fox"',
            ' "quick-brown-fox"\n',
            ' <quick-brown-fox>',
            ' <quick-brown-fox>\n',
            ' <quick-brown-fox> <!-- COMMENT -->',
            ' "quick-brown-fox" <!-- COMMENT -->',
            '"\"1\""',
            ]:
    parsed = value_expr.parseString(s, parseAll=True)
    print(s, '∴', parsed)

for s in [  '# resX\n<!-- COMMENT -->\n\n  * a-b-c: <quick-brown-fox>',
            ]:
    print(s, end='')
    parsed = resource_block.parseString(s, parseAll=True)
    print('∴', parsed)

for s in [  '  * a-b-c: <quick-brown-fox>',
            '  * a-b-c:  quick brown fox',
            '  * a-b-c: " quick brown fox"',
            ]:
    parsed = prop.parseString(s, parseAll=True)
    print(s, '∴', parsed)

for s in [  '# resX\n  * a-b-c: <quick-brown-fox>',
            '# resX [Person]\n  * a-b-c: <quick-brown-fox>',
            '# resX [Person]\n  * a-b-c: <quick-brown-fox>\n  * d-e-f: "lazy dog"',
            ]:
    parsed = resource_block.parseString(s, parseAll=True)
    print(s, '∴', parsed)

for s in [  '# resX\n  * a-b-c: <quick-brown-fox>\n    lang: en',
            ]:
    parsed = resource_block.parseString(s, parseAll=True)
    print(s, '∴', parsed)

for s in [  '# res1\n<!-- COMMENT -->\n\n  * a-b-c: <quick-brown-fox>\n\n\n# res2\n\n  * d-e-f: <jumps-over>\n\n\n',
            ]:
    print(s, end='')
    parsed = resource_block.parseString(s, parseAll=True)
    print('∴', parsed)

for s in [  '# res1\n<!-- COMMENT -->\n\n  * a-b-c: <quick-brown-fox>\n\n\n\n\n# res2\n\n  * d-e-f: <jumps-over>\n\n\n',
            ]:
    print(s, end='')
    parsed = resource_seq.parseString(s, parseAll=True)
    print('∴', parsed)

'''


'''

  a-b-c: <quick-brown-fox> ∴ [prop_info(key='a-b-c', value=ParseResults([I(quick-brown-fox)], {}), children=[ParseResults([], {})])]
  a-b-c:  quick brown fox ∴ [prop_info(key='a-b-c', value=ParseResults(['quick brown fox'], {}), children=[ParseResults([], {})])]
  a-b-c: " quick brown fox" ∴ [prop_info(key='a-b-c', value=ParseResults([LITERAL(' quick brown fox')], {}), children=[ParseResults([], {})])]
# resX
  a-b-c: <quick-brown-fox> ∴ [I(resX), None, prop_info(key='a-b-c', value=ParseResults([I(quick-brown-fox)], {}), children=[ParseResults([], {})])]
# resX [Person]
  a-b-c: <quick-brown-fox> ∴ [I(resX), 'Person', prop_info(key='a-b-c', value=ParseResults([I(quick-brown-fox)], {}), children=[ParseResults([], {})])]
# resX [Person]
  a-b-c: <quick-brown-fox>
  d-e-f: "lazy dog" ∴ [I(resX), 'Person', prop_info(key='a-b-c', value=ParseResults([I(quick-brown-fox)], {}), children=[ParseResults([prop_info(key='d-e-f', value=LITERAL('lazy dog'), children=[])], {})])]
# resX
  a-b-c: <quick-brown-fox>
    lang: en ∴ [I(resX), None, prop_info(key='a-b-c', value=ParseResults([I(quick-brown-fox)], {}), children=[ParseResults([prop_info(key='lang', value='en', children=[])], {})])]

'''
