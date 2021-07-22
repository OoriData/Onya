'''
The main body of the Onya Literate (Markdown flavor) parser

Proper entry point of use is onya.serial.literate

see: doc/literate_format.md

'''

import re
import itertools

import markdown

from amara3 import iri # for absolutize & matches_uri_syntax
from amara3.iri import I
from amara3.uxml import html5
from amara3.uxml.tree import treebuilder, element, text
from amara3.uxml.treeutil import *

from onya.contrib import mkdcomments
from onya.terms import ONYA, ONYA_TYPE
from onya.graph import graph, node

TEXT_VAL, RES_VAL, UNKNOWN_VAL = 1, 2, 3

# Does not support the empty URL <> as a property name
# REL_PAT = re.compile('((<(.+)>)|([@\\-_\\w#/]+)):\s*((<(.+)>)|("(.*?)")|(\'(.*?)\')|(.*))', re.DOTALL)
REL_PAT = re.compile('((<(.+)>)|([@\\-_\\w#/]+)):\s*((<(.+)>)|("(.*)")|(\'(.*)\')|(.*))', re.DOTALL)

# Abbreviated URL patterns
URI_ABBR_PAT = re.compile('@([\\-_\\w]+)([#/@])(.+)', re.DOTALL)
URI_EXPLICIT_PAT = re.compile('<(.+)>', re.DOTALL)

# Does not support the empty URL <> as a property name
RESOURCE_STR = '([^\s\\[\\]]+)?\s?(\\[([^\s\\[\\]]*?)\\])?'
RESOURCE_PAT = re.compile(RESOURCE_STR)
AB_RESOURCE_PAT = re.compile('<\s*' + RESOURCE_STR + '\s*>')

HEADER_PAT = re.compile('h\\d')


class parser:
    '''
    Reusable object for parsing Onya Literate

    Note (and to go in doc) such as doc/literate_format.md

    There are two main base IRIs for relative resolution, schema base and doc base
    schema base is used to resolve schematic/vocabulary elements (i.e. classes and properties)
    doc base is used to resolve entities defined within the doc

    '''
    def __init__(self, config=None, encoding='utf-8'):
        '''
        Translate Onya Literate (Markdown syntax) into an Onya graph

        md -- markdown source text
        g -- Onya graph to take the output relationship
        encoding -- character encoding (defaults to UTF-8)
        '''
        self.config = config or {}
        if config: self.handle_config()
        self.encoding = encoding
        self.comment_ext = mkdcomments.CommentsExtension()
        # Remaining data members reset in run(), but explicitly set here for clarity
        self.schemabase = None # For resolving relative URI references to properties, classes, etc.
        self.rtbase = None
        self.document_iri = None # Source URI of the document being parsed. Also used to resolve relative resource IDs

    def handle_config(self):
        '''
        Configure parser for conventions used to interpret Markdown patterns
        '''
        # Mapping takes syntactical elements such as header levels in Markdown and associates a resource type with the specified resources
        self.syntaxtypemap = {}
        if self.config.get('autotype-h1'): self.syntaxtypemap['h1'] = self.config.get('autotype-h1')
        if self.config.get('autotype-h2'): self.syntaxtypemap['h2'] = self.config.get('autotype-h2')
        if self.config.get('autotype-h3'): self.syntaxtypemap['h3'] = self.config.get('autotype-h3')
        interp_stanza = self.config.get('interpretations', {})
        self.setup_interpretations(interp_stanza)

    def setup_interpretations(self, interp):
        '''
        Parse interpretations stanza in markdown format to update parser config
        '''
        self.interpretations = {}
        # Map interpretation IRIs to functions that perform the data prep at runtime
        for prop, interp_key in interp.items():
            if interp_key.startswith('@'):
                interp_key = iri.absolutize(interp_key[1:], ONYA)
            if interp_key in PREP_METHODS:
                self.interpretations[prop] = PREP_METHODS[interp_key]
            else:
                #just use the identity, i.e. no-op
                self.interpretations[prop] = lambda x, **kwargs: x

    def run(self, littext, g):
        """
        Translate Onya Literate (Markdown syntax) into an Onya graph

        md -- markdown source text
        g -- Onya graph to take the output relationship
        encoding -- character encoding (defaults to UTF-8)

        Returns: Set of nodes defined in the source

        Note: One of the nodes usually represents the graph itself. It should be the
        only node of type @graph (Onya graph). If there are multiple such nodes
        a warning will be issued.
        
        Each generated graph has a propety (`@base`) with the overall base URI specified
        in the Markdown file. If there is no such specification this propety is omitted

        >>> from onya.graph import graph
        >>> from onya.serial.literate import parse
        >>> g = graph()
        >>> parse(open('test/resource/poetry.md').read(), g)
        ...
        >>> len(g)
        3
        """
        self.base = self.schemabase = self.rtbase = \
            self.document_iri = self.default_lang = None
        self.new_nodes = set()
        self.target_graph = g
        self.docheader_node = None
        self.new_nodes = set()

        # Parse the Markdown
        # Alternately:
        # from xml.sax.saxutils import escape, unescape
        # h = markdown.markdown(escape(md.decode(encoding)), output_format='html5')
        # Note: even using safe_mode this should not be presumed safe from tainted input
        # h = markdown.markdown(md.decode(encoding), safe_mode='escape', output_format='html5')
        h = markdown.markdown(littext, safe_mode='escape', output_format='html5', extensions=[self.comment_ext])

        # doc = html.markup_fragment(inputsource.text(h.encode('utf-8')))
        tb = treebuilder()
        h = '<html>' + h + '</html>'
        root = html5.parse(h)
        print(root.xml_encode())
        # Each section contains one resource description, but the special one named @docheader contains info to help interpret the rest
        first_h1 = next(select_name(descendants(root), 'h1'))

        # Doc header element, if any
        docheader = next(select_value(select_name(descendants(root), 'h1'), '@docheader'), None) # //h1[.="@docheader"]
        sections = filter(lambda x: x.xml_value != '@docheader',
                        select_name_pattern(descendants(root), HEADER_PAT)) # //h1[not(.="@docheader")]|h2[not(.="@docheader")]|h3[not(.="@docheader")]

        print(docheader)
        if docheader is not None:
            self.handle_docheader(docheader)

        # Go through the resources expressed in remaining sections
        for sect in sections:
            # header in one of 4 forms: "ResourceID" "ResourceID [ResourceType]" "[ResourceType]" or "[]"
            # 3rd & 4th forms have no ID given in file (type specified or not). One will be assigned
            # XXX Should we require a resource ID?
            matched = RESOURCE_PAT.match(sect.xml_value)
            if not matched:
                raise ValueError(_('Syntax error in resource header: {0}'.format(sect.xml_value)))
            rid = matched.group(1)
            rtype = matched.group(3)
            if rtype and self.schemabase:
                rtype = self.schemabase(rtype)

            if self.base: rid = self.base(rid)

            # Resource type might be set by syntax config
            if not rtype:
                rtype = self.syntaxtypemap.get(sect.xml_name)

            # We have enough info to init the node this section represents
            new_node = self.target_graph.node(rid, rtype)
            self.new_nodes.add(new_node)

            self.fields(sect, new_node)

        return self.docheader_node, self.new_nodes # self.document_iri

    def fields(self, sect, node):
        '''
        Each section represents a resource and contains a list with its properties
        This generator parses the list and yields the key value pairs representing the properties
        Some properties have attributes, expressed in markdown as a nested list. If present these attributes
        Are yielded as well, else None is yielded
        '''
        # Pull all the list elements until the next header. This accommodates multiple lists in a section
        try:
            sect_body_items = itertools.takewhile(lambda x: HEADER_PAT.match(x.xml_name) is None, select_elements(following_siblings(sect)))
        except StopIteration:
            return

        self.process_block(sect_body_items, node, recognize_edges=True)

    def handle_docheader(self, docheader_elem):
        # Special node to hold document header info for processing
        # FIXME: reconsider ID & type
        self.docheader_node = node(ONYA('docheader'), ONYA('docheader'))

        iris = {}

        # Gather document-level metadata from the @docheader section
        fields(docheader_elem, self.docheader_node, None)

        for prop in self.docheader_node.properties:
            # @iri section is where key IRI prefixes can be set
            if prop == '@iri':
                for (k, uri, typeindic) in subfield_list:
                    if k == '@base':
                        self.base = self.schemabase = self.rtbase = uri
                    # @property is legacy
                    elif k == '@schema' or k == '@property':
                        self.schemabase = uri
                    elif k == '@resource-type':
                        self.rtbase = uri
                    else:
                        iris[k] = uri
            # @interpretations section is where defaults can be set as to the primitive types of values from the Markdown, based on the relevant property/relationship
            elif prop == '@interpretations':
                #Iterate over items from the @docheader/@interpretations section to set up for further parsing
                interp = {}
                for k, v, x in subfield_list:
                    interp[I(iri.absolutize(k, schemabase))] = v
                self.setup_interpretations(interp)
            # Setting an IRI for this very document being parsed
            elif prop == '@document':
                self.document_iri = val
            elif prop == '@language':
                self.default_lang = val
            # If we have a resource to which to attach them, just attach all other properties
            elif self.document_iri or self.base:
                rid = self.document_iri or self.base
                fullprop = I(iri.absolutize(prop, self.schemabase or self.base))
                if fullprop in self.interpretations:
                    val = self.interpretations[fullprop](val, rid=rid, fullprop=fullprop, base=base)
                    if val is not None: self.docheader_node.add_property(fullprop, val)
                else:
                    self.docheader_node.add_property(fullprop, val)

        # Default IRI prefixes if @iri/@base is set
        if not self.schemabase: self.schemabase = base
        if not self.rtbase: self.rtbase = base
        if not self.document_iri: self.document_iri = base

    def process_block(self, block, stem, recognize_edges=False):
        block_text = get_block_text(next(block))
        print('GRIPPO', (block_text,))
        label, val, typeindic = parse_block(block_text)
        if label:
            label = expand_iri(label, self.base)
            # Err, what's this logic again?
            # valmatch = URI_ABBR_PAT.match(aval)
            # if valmatch:
            #     uri = iris[valmatch.group(1)]
            #     attrs[fullaprop] = URI_ABBR_PAT.sub(uri + '\\2\\3', aval)
            if typeindic == RES_VAL:
                val = expand_iri(val, self.res_base)
            elif typeindic == TEXT_VAL:
                # FIXME: Handle default lang
                # if '@lang' not in attrs: attrs['@lang'] = default_lang
                pass
            elif typeindic == UNKNOWN_VAL:
                val_iri_match = URI_EXPLICIT_PAT.match(val)
                if val_iri_match:
                    val = expand_iri(val, self.res_base)
                # elif label in self.interpretations:
                #     val = self.interpretations[label](val, rid=rid, fullprop=fullprop, base=base)

            prop = stem.add_property(label, val)

            # Nested list expresses attributes on a property
            li_iter = ( li for elem in select_name(block, 'ul') for li in select_name(elem, 'li') )

            for li in li_iter:
                # Notice recognize_edges is only true at top level
                process_block(li, prop)

        return

def get_block_text(block):
    '''
    Get simplified contents of an block

    a/href embedded in the block comes from Markdown such as `<link_text>`.
    Restore the angle brackets as expected by the li parser
    Also exclude child uls (to be processed separately)
    '''
    return ''.join([
        ( ch if isinstance(ch, text) else (
            '<' + ch.xml_value + '>' if isinstance(ch, element) and ch.xml_name == 'a' else '')
        )
        for ch in itertools.takewhile(
            lambda x: not (isinstance(x, element) and x.xml_name == 'ul'), block.xml_children
        )
    ])


def parse_block(btext):
    '''
    Parse each list item into a property pair
    '''
    if btext.strip():
        matched = REL_PAT.match(btext)
        if not matched:
            raise ValueError(_('Syntax error in relationship expression: {0}'.format(pair)))
        if matched.group(3): prop = matched.group(3).strip()
        if matched.group(4): prop = matched.group(4).strip()
        if matched.group(7):
            val = matched.group(7).strip()
            typeindic = RES_VAL
        elif matched.group(9):
            val = matched.group(9).strip()
            typeindic = TEXT_VAL
        elif matched.group(11):
            val = matched.group(11).strip()
            typeindic = TEXT_VAL
        elif matched.group(12):
            val = matched.group(12).strip()
            typeindic = UNKNOWN_VAL
        else:
            val = ''
            typeindic = UNKNOWN_VAL
        # prop, val = [ part.strip() for part in U(li.xml_select('string(.)')).split(':', 1) ]
        return prop, val, typeindic
    return None, None, None


def expand_iri(iri_in, base):
    if iri_in.startswith('@'):
        return ONYA(iri_in[1:])
    iri_match = URI_EXPLICIT_PAT.match(iri_in)
    if iri_match:
        return base(iri_match.group(1))
    iri_match = URI_ABBR_PAT.match(iri_in)
    if iri_match:
        uri = iris[iri_match.group(1)]
        fulliri = URI_ABBR_PAT.sub(uri + '\\2\\3', iri_in)
    else:
        fulliri = I(iri.absolutize(iri_in, base))
    return fulliri


# FIXME: Rethink. Uses anonymous nodes
def handle_resourcelist(ltext, **kwargs):
    '''
    Helper converts lists of resources from text (i.e. Markdown),
    including absolutizing relative IRIs
    '''
    base = kwargs.get('base', ONYA)
    g = kwargs.get('graph')
    iris = ltext.strip().split()
    newlist = g.node()
    for i in iris:
        model.add(newlist, ONYA('item'), base(i))
    return newlist


# FIXME: Rethink. Uses anonymous nodes
def handle_resourceset(ltext, **kwargs):
    '''
    Helper converts lists of resources from text (i.e. Markdown),
    including absolutizing relative IRIs
    '''
    fullprop=kwargs.get('fullprop')
    rid=kwargs.get('rid')
    base=kwargs.get('base', ONYA)
    model=kwargs.get('model')
    iris = ltext.strip().split()
    for i in iris:
        model.add(rid, fullprop, I(iri.absolutize(i, base)))
    return None


PREP_METHODS = {
    ONYA('text'): lambda x, **kwargs: x,
    ONYA('resource'): lambda x, base=ONYA, **kwargs: I(iri.absolutize(x, base)),
    ONYA('resourceset'): handle_resourceset,
}

