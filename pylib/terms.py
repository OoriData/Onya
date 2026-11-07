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
ONYA_METHOD_REL = ONYA('method')  # @method provenance sub-edge (points to a node identifying the method)
ONYA_CONFIDENCE_REL = ONYA('confidence')  # @confidence provenance sub-property, nested under @method
ONYA_ASOF = ONYA('asOf')  # @asOf: ISO 8601 time an assertion was true at, nested under it (core: not only circum)
ONYA_DOCUMENT = ONYA('Document')  # Type for document nodes created from @document directive
ONYA_ASSERTION = ONYA('Assertion')  # Implicit type carried by every assertion (edge/property)

# The remaining core reserved terms, one constant each (see RESERVED, and SPEC: Reserved vocabulary).
# Docheader directives:
ONYA_DOCUMENT_REL = ONYA('document')  # @document
ONYA_NODEBASE = ONYA('nodebase')  # @nodebase
ONYA_BASE = ONYA('base')  # @base (alias of @nodebase)
ONYA_SCHEMA = ONYA('schema')  # @schema
ONYA_TYPEBASE = ONYA('typebase')  # @typebase
ONYA_LANGUAGE = ONYA('language')  # @language
ONYA_IRI = ONYA('iri')  # @iri (prefix stanza)
ONYA_INTERPRETATIONS = ONYA('interpretations')  # @interpretations (default-interpretation stanza)
# Assertion directives (consumed by the parser; they set `id` / `interp`, and are not stored as assertions):
ONYA_ID = ONYA('id')  # @id
ONYA_AS = ONYA('as')  # @as

# The ordering layer's terms (see onya.ordering). Reserved here, with the layer's name, so that a graph
# using them isn't reported by `unknown_reserved_terms` whether or not `onya.ordering` was imported.
ONYA_ORDERING = ONYA('ordering')  # @ordering: a nested integer giving an occurrence's position
ONYA_ORDERED = ONYA('ordered')  # @ordered: docheader stanza naming labels to stamp from document order

# The shape layer's terms (see onya.shape): classes and properties declared as nodes, and what they say.
ONYA_CLASS = ONYA('Class')  # type of a class declaration
ONYA_PROPERTY = ONYA('Property')  # type of a property declaration (its node id is the label IRI)
ONYA_LABEL = ONYA('label')  # @label: a human-readable name
ONYA_SUBCLASSOF = ONYA('subClassOf')  # @subClassOf -> Class
ONYA_APPLIESTO = ONYA('appliesTo')  # @appliesTo -> Class (any of)
ONYA_RANGE = ONYA('range')  # @range -> Class (any of): the property is an edge
ONYA_CARDINALITY = ONYA('cardinality')  # @cardinality: 1 | 0..1 | 1..* | 0..* | n..m
ONYA_ONEOF = ONYA('oneOf')  # @oneOf: an allowed value (repeat for each)
ONYA_CLOSED = ONYA('closed')  # @closed: true on a Class: undeclared labels are findings
ONYA_SEVERITY = ONYA('severity')  # @severity: error | warning
ONYA_TABLE = ONYA('table')  # @table: override a derived table name (onya.circum)
ONYA_COLUMN = ONYA('column')  # @column: override a derived column name (onya.circum)
# The circum layer's read side (see onya.circum): sidecars are declared as nodes, and circum properties point at them
ONYA_SIDECAR = ONYA('Sidecar')  # type of a sidecar declaration: where some properties' values are held
ONYA_SYSTEM = ONYA('System')  # type of the system a sidecar lives in
ONYA_SYSTEM_REL = ONYA('system')  # @system -> System
ONYA_CIRCUMQUERY = ONYA('circumQuery')  # on a @Property: -> the @Sidecar holding its values
ONYA_QUERYDETAIL = ONYA('queryDetail')  # nested under @circumQuery: opaque to Onya, passed to the resolver
ONYA_SENSITIVITY = ONYA('sensitivity')  # @sensitivity on a sidecar: what a policy decides access by
ONYA_RETENTION = ONYA('retention')  # @retention on a sidecar: how long its rows are kept

# Reserved vocabulary. Every `@x` in Onya Literate is the IRI `onya:x` (http://purl.org/onya/vocab/x).
# RESERVED maps each reserved local name to the layer that defines it: 'core' for the terms above, and
# the layer's own name for terms a layer adds (via `reserve`, from that layer's module). Layers extend the
# core vocabulary without a registry edit here, but may not reuse a name another layer already holds.
RESERVED: dict[str, str] = {}


def reserve(layer: str, *names: str) -> None:
    '''
    Register `names` (local names, without the `@`) as reserved vocabulary defined by `layer`.
    Idempotent for the same layer; raises ValueError if a name is already reserved by a different
    layer (a layer must not reuse a term another layer, or core, defines).
    '''
    for name in names:
        held = RESERVED.setdefault(name, layer)
        if held != layer:
            raise ValueError(f'@{name} is already reserved by {held!r}; layer {layer!r} cannot redefine it')


reserve('core',
        'document', 'nodebase', 'base', 'schema', 'typebase', 'language', 'iri', 'interpretations',  # directives
        'id', 'as',  # assertion directives
        'source', 'method', 'confidence', 'asOf',  # provenance
        'Document', 'Assertion',  # implicit types
        'type')  # the type relation: reserved, with no behavior defined yet
reserve('ordering', 'ordering', 'ordered')  # onya.ordering (not core: see SPEC, Reserved vocabulary)
reserve('shape', 'Class', 'Property', 'label', 'subClassOf', 'appliesTo', 'range', 'cardinality', 'oneOf',
        'closed', 'severity')  # onya.shape
reserve('circum', 'table', 'column', 'Sidecar', 'System', 'system', 'circumQuery', 'queryDetail', 'sensitivity',
        'retention')  # onya.circum


def unknown_reserved_terms(g) -> dict:
    '''
    Terms in `g` that live in the Onya vocabulary (`@x`, i.e. `onya:x`) but that neither core nor
    any loaded layer reserves: almost always a typo (`@Calss`). Maps each such IRI to its uses: the
    assertions it labels, and the nodes it types. Findings are data, never errors; parsing accepts
    any `@x`, since a layer you haven't loaded may define it (SPEC: Reserved vocabulary).

    Interpretation IRIs (`onya:interp/...`) are a separate namespace, audited by
    `onya.interp.unknown_interps`.
    '''
    found: dict = {}
    base = str(ONYA)

    def check(term, use) -> None:
        local = str(term)[len(base):] if str(term).startswith(base) else None
        if local and '/' not in local and '#' not in local and local not in RESERVED:
            found.setdefault(I(str(term)), []).append(use)

    def walk(container) -> None:
        for a in (*container.properties, *container.edges):
            check(a.label, a)
            walk(a)

    for n in g.nodes.values():
        for t in n.types:
            check(t, n)
        walk(n)
    return found

# Onya interpretation vocabulary (the data-contract "interpretation" names). `@as: number`
# and the reserved docheader interpretation names resolve here: e.g.
# ONYA_INTERP('number') -> http://purl.org/onya/vocab/interp/number. These IRIs name the
# Onya Lightweight Types starter set honored by onya.interp.DEFAULT.
ONYA_INTERP = ONYA('interp/')

# The reserved bare interpretation names (see SPEC: @as). `none` is special — it names no
# interpretation and only cancels a docheader default; it is never stored as an IRI.
RESERVED_INTERP_NAMES = frozenset({'number', 'integer', 'datetime', 'boolean', 'iri', 'text'})
INTERP_NONE = 'none'

# RDF

RDF_NS = I('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS_NS = I('http://www.w3.org/2000/01/rdf-schema#')

RDF_TYPE = RDF_NS('type')
