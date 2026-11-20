# -*- coding: utf-8 -*-
# test/test_shape_against_circum.py
'''
#88: `validate(..., against=base)` and `validate(g, shapes=<compiled Shapes>)` with a circum property in the shapes.
They used to raise `AttributeError: 'Shapes' object has no attribute 'nodes'`.
'''

from onya.circum import Registry, Text, augment
from onya.graph import graph
from onya.serial.literate import read
from onya.shape import load_shapes, validate

NS = 'http://e.o/'
GPA = NS + 'gpa'

HEAD = '# @docheader\n* @document: http://e.o/doc\n* @nodebase: http://e.o/\n* @schema: http://e.o/\n\n'

SHAPES = HEAD + '''# Person [@Class]

# name [@Property]
* @appliesTo -> Person
* @cardinality: 1

# gpa [@Property]
* @appliesTo -> Person
* @cardinality: 1
* @circumQuery -> grades

# grades [@Sidecar]
* @system -> registrar

# registrar [@System]
'''

PEOPLE = '# ada [Person]\n* name: Ada\n\n# bo [Person]\n* name: Bo\n'


def _g(text):
    g = graph()
    read(text, g)
    return g


def _gpa_findings(report):
    return sorted(str(f.node).rsplit('/', 1)[1] for f in report.findings if f.kind == 'cardinality' and f.label == GPA)


def test_a_fragment_checked_against_a_base_that_declares_a_circum_property():
    base = _g(SHAPES + PEOPLE)  # no shapes= given: the base's own declarations are used
    fragment = _g(HEAD + '# ada [Person]\n* name: Ada L.\n')
    report = validate(fragment, against=base)  # raised AttributeError
    # `name` is cardinality 1, and the base has one: a second makes two. `gpa` is held in a sidecar, so not "missing"
    assert [f.kind for f in report.findings] == ['cardinality'] and report.findings[0].label == NS + 'name'


def test_a_fragment_with_shapes_given_as_a_graph():
    report = validate(_g(HEAD + '# ada [Person]\n* name: Ada\n'), _g(SHAPES), against=_g(HEAD + PEOPLE))
    assert report.ok


def test_compiled_shapes_given_directly():
    g = _g(HEAD + PEOPLE)
    assert validate(g, load_shapes(_g(SHAPES))).ok  # raised AttributeError
    assert validate(g, _g(SHAPES)).ok  # and a graph still works


async def test_a_view_is_checked_with_compiled_shapes_as_with_a_graph():
    '''The view-only `@cardinality` minimum of a circum property needs the sidecar from the shapes alone.'''
    reg = Registry()

    async def resolver(subjects, ctx):
        return {NS + 'ada': [Text('3.9')]}  # a row for ada only; bo has none

    reg.resolvers[GPA] = resolver
    data = _g(SHAPES + PEOPLE)
    view = await augment(data, registry=reg)
    assert _gpa_findings(validate(view)) == ['bo']  # shapes in the graph itself
    assert _gpa_findings(validate(view, load_shapes(data))) == ['bo']  # compiled: used to raise
    assert _gpa_findings(validate(data)) == []  # not a view: the value is in the sidecar, not missing
    assert _gpa_findings(validate(data, load_shapes(data))) == []


def test_circum_declaration_problems_need_the_graph_and_are_skipped_without_one():
    broken = SHAPES.replace('@circumQuery -> grades', '@circumQuery -> nowhere')
    data = _g(HEAD + PEOPLE)
    assert [f.kind for f in validate(data, _g(broken)).findings] == ['circum']  # a graph: the problem is reported
    assert validate(data, load_shapes(_g(broken))).ok  # compiled Shapes have no sidecar nodes to check
