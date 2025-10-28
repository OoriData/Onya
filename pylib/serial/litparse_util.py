# -*- coding: utf-8 -*-
# onya.serial.litparse_util.py
'''
Utility wrapper for Onya Literate parser

Provides a simple interface to the pyparsing-based parser in literate_lex
'''

from onya.serial import literate_lex


class parser:
    '''
    Reusable object for parsing Onya Literate

    This is a simple wrapper around the pyparsing-based parser
    implementation in literate_lex.
    '''
    def __init__(self, config=None, encoding='utf-8'):
        '''
        Initialize the parser

        config -- optional configuration dict
        encoding -- character encoding (defaults to UTF-8)
        '''
        self.config = config or {}
        self.encoding = encoding

    def run(self, lit_text, g):
        '''
        Parse Onya Literate text into an Onya graph

        lit_text -- Onya Literate source text
        g -- Onya graph to populate with parsed relationships
        encoding -- character encoding (defaults to UTF-8)

        Returns: tuple of (docheader, nodes) where:
            - docheader: document header info (may be None)
            - nodes: set of nodes parsed from the document
        '''
        # Parse the literate text using the pyparsing implementation
        doc_iri = literate_lex.parse(lit_text, g, encoding=self.encoding)

        # For now, return None for docheader and empty set for nodes
        # The pyparsing implementation populates the graph directly
        # TODO: Track nodes that were added during parsing
        docheader = None
        nodes = set()

        return docheader, nodes
