# onya

'''
Onya - Property graph model for Web resources
'''

from .__about__ import __version__
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

