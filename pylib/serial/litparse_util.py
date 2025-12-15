# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.litparse_util
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
        op = literate_lex.LiterateParser(
            document_source_assertions=bool(self.config.get('document_source_assertions', False)),
            encoding=self.encoding,
        )
        result = op.parse(lit_text, g)
        # Return doc_iri as docheader (for compatibility)
        return result.doc_iri, result.nodes_added
