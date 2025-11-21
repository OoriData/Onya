# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya

'''
Onya - Property graph model for Web resources
'''

from .__about__ import __version__ as __version__  # noqa: F401
from amara.iri import I

# Base IRI for Onya vocabulary
ONYA_BASEIRI = I('http://purl.org/onya/vocab/')

# Special null value for Onya
ONYA_NULL = I('http://purl.org/onya/vocab/null')


class LITERAL:
    '''
    Wrapper for literal (text) values in Onya
    '''
    def __init__(self, s):
        self._s = s

    def __str__(self):
        return self._s

    def __repr__(self):
        return f'LITERAL({repr(self._s)})'

