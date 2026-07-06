# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.terms
'''
Commonly used IRIs as vocabulary terms
'''

from amara.iri import I

# Onya

ONYA = I('http://purl.org/onya/vocab/')
ONYA_TYPE_REL = ONYA('type')
ONYA_SOURCE_REL = ONYA('source')  # @source provenance sub-property
ONYA_DOCUMENT = ONYA('Document')  # Type for document nodes created from @document directive
ONYA_ASSERTION = ONYA('Assertion')  # Implicit type carried by every assertion (edge/property)

# RDF

RDF_NS = I('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS_NS = I('http://www.w3.org/2000/01/rdf-schema#')

RDF_TYPE = RDF_NS('type')
