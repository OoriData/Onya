# -*- coding: utf-8 -*-
# test_serial_mermaid.py
'''
Test Onya Mermaid serializer

pytest test/test_serial_mermaid.py
pytest -s test/test_serial_mermaid.py  # With console output
'''

from io import StringIO

from onya.graph import graph
from onya.serial import mermaid


def test_basic_mermaid_output():
    '''Test basic Mermaid flowchart output with nodes and edges'''
    g = graph()

    chuks = g.node('http://example.org/people/Chuks', 'http://schema.org/Person')
    ify = g.node('http://example.org/people/Ify', 'http://schema.org/Person')

    chuks.add_property('http://schema.org/name', 'Chukwuemeka Okafor')
    chuks.add_property('http://schema.org/birthDate', '1985-03-15')
    ify.add_property('http://schema.org/name', 'Ifeoma Eze')

    chuks.add_edge('http://schema.org/knows', ify)

    out = StringIO()
    mermaid.write(g, out=out)
    mm = out.getvalue()

    assert 'flowchart TB' in mm
    assert '-->' in mm
    assert 'http://example.org/people/Chuks' in mm
    assert 'http://example.org/people/Ify' in mm
    assert 'Chukwuemeka Okafor' in mm or 'name' in mm


def test_mermaid_with_reified_edge_annotations():
    '''Test Mermaid output with edge annotations (reified relationship properties)'''
    g = graph()

    chuks = g.node('http://example.org/people/Chuks', 'http://schema.org/Person')
    ify = g.node('http://example.org/people/Ify', 'http://schema.org/Person')

    friendship = chuks.add_edge('http://schema.org/knows', ify)
    friendship.add_property('http://schema.org/startDate', '2018-03-15')
    friendship.add_property('http://schema.org/description', 'Met at university')

    out = StringIO()
    mermaid.write(g, out=out, show_edge_annotations=True)
    mm = out.getvalue()

    assert '2018-03-15' in mm or 'startDate' in mm


def test_mermaid_layout_options():
    '''Test different Mermaid directions'''
    g = graph()
    a = g.node('http://example.org/A')
    b = g.node('http://example.org/B')
    a.add_edge('http://example.org/linksTo', b)

    out = StringIO()
    mermaid.write(g, out=out, rankdir='LR')
    mm = out.getvalue()

    assert 'flowchart LR' in mm


def test_mermaid_without_properties():
    '''Test Mermaid output with properties hidden'''
    g = graph()
    node1 = g.node('http://example.org/Node1')
    node1.add_property('http://example.org/prop', 'value')

    out = StringIO()
    mermaid.write(g, out=out, show_properties=False)
    mm = out.getvalue()

    assert 'flowchart TB' in mm
    assert 'value' not in mm


def test_mermaid_edge_without_label():
    '''Test edges emitted without labels'''
    g = graph()
    a = g.node('http://example.org/A')
    b = g.node('http://example.org/B')
    a.add_edge('http://example.org/linksTo', b)

    out = StringIO()
    mermaid.write(g, out=out, show_edge_labels=False)
    mm = out.getvalue()

    assert '-->' in mm
    assert '-- "' not in mm


def test_mermaid_with_types_display():
    '''Test that node types are displayed in labels'''
    g = graph()
    node1 = g.node('http://example.org/Chuks',
                   ['http://schema.org/Person', 'http://example.org/Employee'])
    node1.add_property('http://schema.org/name', 'Chuks')

    out = StringIO()
    mermaid.write(g, out=out, show_types=True)
    mm = out.getvalue()

    assert 'Person' in mm or 'http://schema.org/Person' in mm


def test_mermaid_custom_shapes():
    '''Test basic custom node shape mapping by type'''
    g = graph()
    person = g.node('http://example.org/Chuks', 'http://schema.org/Person')
    org = g.node('http://example.org/ACME', 'http://schema.org/Organization')
    person.add_edge('http://schema.org/worksFor', org)

    out = StringIO()
    mermaid.write(g, out=out,
                 node_shapes={
                     'http://schema.org/Person': 'round',
                     'http://schema.org/Organization': 'box',
                 })
    mm = out.getvalue()

    # round uses parentheses
    assert '(' in mm


if __name__ == '__main__':
    test_basic_mermaid_output()
    print('✓ test_basic_mermaid_output passed')

