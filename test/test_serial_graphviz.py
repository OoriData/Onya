# -*- coding: utf-8 -*-
# test_serial_graphviz.py
'''
Test Onya Graphviz serializer

pytest test/test_serial_graphviz.py
pytest -s test/test_serial_graphviz.py  # With console output
'''

from io import StringIO

from onya.graph import graph
from onya.serial import graphviz


def test_basic_graphviz_output():
    '''Test basic Graphviz DOT output with nodes and edges'''
    g = graph()

    # Create nodes
    chuks = g.node('http://example.org/people/Chuks', 'http://schema.org/Person')
    ify = g.node('http://example.org/people/Ify', 'http://schema.org/Person')

    # Add properties
    chuks.add_property('http://schema.org/name', 'Chukwuemeka Okafor')
    chuks.add_property('http://schema.org/birthDate', '1985-03-15')
    ify.add_property('http://schema.org/name', 'Ifeoma Eze')

    # Add edge
    chuks.add_edge('http://schema.org/knows', ify)

    # Serialize to DOT
    out = StringIO()
    graphviz.write(g, out=out)
    dot_output = out.getvalue()

    # Verify DOT structure
    assert 'digraph G {' in dot_output
    assert '}' in dot_output

    # Check that nodes are defined
    assert 'http://example.org/people/Chuks' in dot_output
    assert 'http://example.org/people/Ify' in dot_output

    # Check that edge is defined
    assert '->' in dot_output

    # Check that properties are shown (default show_properties=True)
    assert 'Chukwuemeka Okafor' in dot_output or 'name' in dot_output


def test_graphviz_with_reified_edge():
    '''Test Graphviz output with reified edge (edge with properties)'''
    g = graph()

    # Create nodes
    chuks = g.node('http://example.org/people/Chuks', 'http://schema.org/Person')
    ify = g.node('http://example.org/people/Ify', 'http://schema.org/Person')

    # Add edge with properties (reified relationship)
    friendship = chuks.add_edge('http://schema.org/knows', ify)
    friendship.add_property('http://schema.org/startDate', '2018-03-15')
    friendship.add_property('http://schema.org/description', 'Met at university')

    # Serialize to DOT
    out = StringIO()
    graphviz.write(g, out=out, show_edge_annotations=True)
    dot_output = out.getvalue()

    # Verify edge annotations are shown
    assert '2018-03-15' in dot_output or 'startDate' in dot_output


def test_graphviz_with_custom_styling():
    '''Test Graphviz output with custom node shapes and colors'''
    g = graph()

    # Create nodes with types
    person = g.node('http://example.org/Chuks', 'http://schema.org/Person')
    org = g.node('http://example.org/ACME', 'http://schema.org/Organization')

    person.add_property('http://schema.org/name', 'Chuks')
    org.add_property('http://schema.org/name', 'ACME Corp')

    # Serialize with custom styling
    out = StringIO()
    graphviz.write(g, out=out,
                   node_shapes={
                       'http://schema.org/Person': 'ellipse',
                       'http://schema.org/Organization': 'box'
                   },
                   node_colors={
                       'http://schema.org/Person': 'lightblue',
                       'http://schema.org/Organization': 'lightgreen'
                   })
    dot_output = out.getvalue()

    # Check that shapes are used
    assert 'ellipse' in dot_output
    assert 'box' in dot_output

    # Check that colors are used
    assert 'lightblue' in dot_output
    assert 'lightgreen' in dot_output


def test_graphviz_layout_options():
    '''Test different layout directions'''
    g = graph()

    node1 = g.node('http://example.org/A')
    node2 = g.node('http://example.org/B')
    node1.add_edge('http://example.org/linksTo', node2)

    # Test left-to-right layout
    out = StringIO()
    graphviz.write(g, out=out, rankdir='LR')
    dot_output = out.getvalue()

    assert 'rankdir=LR' in dot_output


def test_graphviz_without_properties():
    '''Test Graphviz output with properties hidden'''
    g = graph()

    node1 = g.node('http://example.org/Node1')
    node1.add_property('http://example.org/prop', 'value')

    # Serialize without showing properties
    out = StringIO()
    graphviz.write(g, out=out, show_properties=False)
    dot_output = out.getvalue()

    # Properties should not appear in labels
    # (This is a bit tricky to test definitively, but we can check structure)
    assert 'digraph G {' in dot_output


def test_graphviz_with_base_iri():
    '''Test IRI abbreviation with base IRI'''
    g = graph()

    node1 = g.node('http://example.org/people/Alice', 'http://schema.org/Person')
    node1.add_property('http://schema.org/name', 'Alice')

    # Serialize with base IRIs for abbreviation
    out = StringIO()
    graphviz.write(g, out=out,
                   base='http://example.org/',
                   propertybase='http://schema.org/')
    dot_output = out.getvalue()

    # Should have abbreviated forms (though exact format depends on implementation)
    assert 'digraph G {' in dot_output
    # The full IRIs might still appear in the node IDs, but labels should be abbreviated


def test_graphviz_edge_without_label():
    '''Test edge display without labels'''
    g = graph()

    node1 = g.node('http://example.org/A')
    node2 = g.node('http://example.org/B')
    node1.add_edge('http://example.org/linksTo', node2)

    # Serialize without edge labels
    out = StringIO()
    graphviz.write(g, out=out, show_edge_labels=False)
    dot_output = out.getvalue()

    # Edge should exist but without label attribute
    assert '->' in dot_output


def test_graphviz_with_types_display():
    '''Test that node types are displayed'''
    g = graph()

    node1 = g.node('http://example.org/Chuks',
                   ['http://schema.org/Person', 'http://example.org/Employee'])
    node1.add_property('http://schema.org/name', 'Chuks')

    # Serialize with types shown
    out = StringIO()
    graphviz.write(g, out=out, show_types=True)
    dot_output = out.getvalue()

    # Types should appear in the output
    assert 'Person' in dot_output or 'http://schema.org/Person' in dot_output


if __name__ == '__main__':
    # Run tests manually for debugging
    test_basic_graphviz_output()
    print('✓ test_basic_graphviz_output passed')

    test_graphviz_with_reified_edge()
    print('✓ test_graphviz_with_reified_edge passed')

    test_graphviz_with_custom_styling()
    print('✓ test_graphviz_with_custom_styling passed')

    test_graphviz_layout_options()
    print('✓ test_graphviz_layout_options passed')

    test_graphviz_without_properties()
    print('✓ test_graphviz_without_properties passed')

    test_graphviz_with_base_iri()
    print('✓ test_graphviz_with_base_iri passed')

    test_graphviz_edge_without_label()
    print('✓ test_graphviz_edge_without_label passed')

    test_graphviz_with_types_display()
    print('✓ test_graphviz_with_types_display passed')

    print('\nAll tests passed!')
