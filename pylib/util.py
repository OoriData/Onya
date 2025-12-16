# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.util
from amara import iri

from onya import ONYA_BASEIRI

__all__ = ['abbreviate']


def abbreviate(rel, bases):
    '''Abbreviate an IRI using base IRIs for more readable labels'''
    for base in bases:
        abbr = iri.relativize(rel, base, subPathOnly=True)
        if abbr:
            if base is ONYA_BASEIRI:
                abbr = '@' + abbr
            return abbr
    # If no abbreviation found, use the full IRI
    return str(rel)
