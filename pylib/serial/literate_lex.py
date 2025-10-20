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

from onya import I, ONYA_BASEIRI, ONYA_NULL

URI_ABBR_PAT = re.compile('@([\\-_\\w]+)([#/@])(.+)', re.DOTALL)
URI_EXPLICIT_PAT = re.compile('<(.+)>', re.DOTALL)

TYPE_REL = ONYA_BASEIRI('type')

class value_type(Enum):
    '''
    Basic typing info for values (really just text vs resource)
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


@dataclass
class doc_info:
    iri: str = None         # iri of the doc being parsed, itself
    resbase: str = None     # used to resolve relative resource IRIs
    schemabase: str = None  # used to resolve relative schema IRIs
    rtbase: str = None      # used to resolve relative resource type IRIs. 
    lang: str = None        # other IRI abbreviations
    iris: dict = None       # iterpretations of untyped values (e.g. string vs list of strs vs IRI)


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

COMMENT         = cpp_style_comment | htmlComment
OPCOMMENT       = Optional(COMMENT)
IDENT           = Word(alphas, alphanums + '_' + '-')
IDENT_KEY       = Combine(Optional('@') + IDENT).leaveWhitespace()
# EXPLICIT_IRI    = QuotedString('<', end_quote_char='>')
QUOTED_STRING   = MatchFirst((QuotedString('"', escChar='\\'), QuotedString("'", escChar='\\'))) \
                    .setParseAction(literal_parse_action)
# See: https://rdflib.readthedocs.io/en/stable/_modules/rdflib/plugins/sparql/parser.html
IRIREF          = Regex(r'[^<>"{}|^`\\\[\]%s]*' % "".join(
                        "\\x%02X" % i for i in range(33)
                    )) \
                    .setParseAction(iriref_parse_action)
#REST_OF_LINE = rest_of_line.leave_whitespace()

blank_to_eol    = ZeroOrMore(COMMENT) + White('\n')
explicit_iriref = Combine(Suppress("<") + IRIREF + Suppress(">")) \
                    .setParseAction(iriref_parse_action)

value_expr      = ( explicit_iriref + Suppress(ZeroOrMore(COMMENT)) ) | ( QUOTED_STRING + Suppress(ZeroOrMore(COMMENT)) ) | rest_of_line
prop            = Optional(White(' \t').leaveWhitespace(), '') + Suppress('*' + White()) + \
                    ( explicit_iriref | IDENT_KEY | IRIREF ) + Suppress(':') + Optional(value_expr, None)
edge            = Optional(White(' \t').leaveWhitespace(), '') + Suppress('*' + White()) + \
                    ( explicit_iriref | IDENT_KEY | IRIREF ) + Suppress(RIGHT_ARROW) + Optional(value_expr, None)
propset         = Group(delimited_list(prop | edge | COMMENT, delim='\n'))
resource_header = Word('#') + Optional(IRIREF, None) + Optional(QuotedString('[', end_quote_char=']'), None)
resource_block  = Forward()
resource_block  << Group(resource_header + White('\n').suppress() + Suppress(ZeroOrMore(blank_to_eol)) + propset)

# Start symbol
resource_seq    = OneOrMore(
                    Suppress(ZeroOrMore(blank_to_eol)) + \
                        resource_block + White('\n').suppress() + \
                            Suppress(ZeroOrMore(blank_to_eol))
                    )

prop.setParseAction(_make_tree)
edge.setParseAction(_make_tree)
value_expr.setParseAction(_make_value)
# subprop.setParseAction(_make_tree)


def parse(lit_text, model, encoding='utf-8'):
    """
    Translate Onya Literate text into Onya model relationships

    lit_text -- Onya Literate source text
    model -- Onya model to take the output relationship
    encoding -- character encoding (defaults to UTF-8)

    Returns: The overall base URI (`@base`), as specified in the model, or None

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

    parsed = resource_seq.parseString(lit_text, parseAll=True)

    for resblock in parsed:
        process_resblock(resblock, model, doc)

    return doc.iri


def expand_iri(iri_in, base, relcontext=None):
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
        if relcontext and not(iri.matches_uri_ref_syntax(iri_in)):
            # FIXME: Replace with a Onya-specific error
            raise ValueError(f'Invalid IRI reference provided for relation {relcontext}: "{iri_in}"')
        fulliri = iri_in if base is None else I(iri.absolutize(iri_in, base))
    return I(fulliri)


def process_resblock(resblock, model, doc):
    headermarks, rid, rtype, props = resblock
    headdepth = len(headermarks)
    print('RESBLOCK:', resblock)

    if rid == '@docheader':
        process_docheader(props, model, doc)
        return

    rid = expand_iri(rid, doc.resbase)
    # typeindic = RES_VAL | TEXT_VAL | UNKNOWN_VAL
    # FIXME: Use syntaxtypemap
    if rtype:
        model.add(rid, TYPE_REL, expand_iri(rtype, doc.schemabase))

    outer_indent = -1
    current_outer_prop = None
    for prop in props:
        print('PROP:', prop)
        if isinstance(prop, str):
            #Just a comment. Skip.
            continue

        # @iri section is where key IRI prefixes can be set
        # First property encountered determines outer indent
        if outer_indent == -1:
            outer_indent = prop.indent

        if prop.indent == outer_indent:
            if current_outer_prop:
                model.add(rid, current_outer_prop.key, current_outer_prop.value, attrs)

            current_outer_prop = prop
            attrs = {}

            pname = prop.key
            prop.key = expand_iri(pname, doc.schemabase)
            if prop.value:
                prop.value, typeindic = prop.value.verbatim, prop.value.typeindic
                if typeindic == value_type.RES_VAL:
                    prop.value = expand_iri(prop.value, doc.rtbase, relcontext=prop.key)
                elif typeindic == value_type.TEXT_VAL:
                    prop.value = str(prop.value)
                    if '@lang' not in attrs and doc.lang:
                        attrs['@lang'] = doc.lang

        else:
            aprop, aval, atype = prop.key, prop.value, value_type.UNKNOWN_VAL
            aval, typeindic = aval.verbatim, aval.typeindic
            fullaprop = expand_iri(aprop, doc.schemabase)
            if atype == value_type.RES_VAL:
                aval = expand_iri(aval, doc.rtbase)
                valmatch = URI_ABBR_PAT.match(aval)
                if valmatch:
                    uri = doc.iris[I(valmatch.group(1))]
                    attrs[fullaprop] = I(URI_ABBR_PAT.sub(uri + '\\2\\3', aval))
                else:
                    attrs[fullaprop] = I(iri.absolutize(aval, doc.rtbase))
            elif atype == value_type.TEXT_VAL:
                attrs[fullaprop] = str(aval)
            elif atype == value_type.UNKNOWN_VAL:
                val_iri_match = URI_EXPLICIT_PAT.match(str(aval))
                if val_iri_match:
                    aval = expand_iri(aval, doc.rtbase)
                else:
                    aval = str(aval)
                if aval is not None:
                    attrs[fullaprop] = aval

    # Don't forget the final fencepost property
    if current_outer_prop:
        model.add(rid, current_outer_prop.key, current_outer_prop.value, attrs)


def process_docheader(props, model, doc):
    outer_indent = -1
    current_outer_prop = None
    for prop in props:
        # @iri section is where key IRI prefixes can be set
        # First property encountered determines outer indent
        if outer_indent == -1:
            outer_indent = prop.indent
        if prop.indent == outer_indent:
            current_outer_prop = prop
            #Setting an IRI for this very document being parsed
            if prop.key == '@document':
                doc.iri = prop.value.verbatim
            elif prop.key == '@language':
                doc.lang = prop.value.verbatim
            #If we have a resource to which to attach them, just attach all other properties
            elif doc.iri:
                fullprop = I(iri.absolutize(prop.key, doc.schemabase))
                model.add(doc.iri, fullprop, prop.value.verbatim)
        elif current_outer_prop.key == '@iri':
            k, uri = prop.key, prop.value.verbatim
            if k == '@base':
                doc.resbase = doc.rtbase = uri
            elif k == '@schema':
                doc.schemabase = uri
            elif k == '@resource-type':
                doc.rtbase = uri
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
