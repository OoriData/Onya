# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.graphviz

'''
Serialize an Onya model to Graphviz DOT format for high-quality static visualizations

Example usage:
    from onya.graph import graph
    from onya.serial import graphviz

    g = graph()
    # … populate graph …

    # Basic usage
    with open('output.dot', 'w') as f:
        graphviz.write(g, out=f)

    # With custom styling
    graphviz.write(g, out=f,
                   rankdir='LR',
                   show_properties=True,
                   node_shapes={'http://schema.org/Person': 'ellipse'})

Note: See also demo/graphviz_basic/graphviz_demo.py for more info, including on installling graphviz.
'''

import sys
import html

from onya.util import abbreviate, ONYA_BASEIRI

__all__ = ['write']


def escape_dot_id(s):
    '''
    Escape a string for use as a DOT identifier
    DOT identifiers can be:
    - Alphanumeric + underscore (no quotes needed)
    - Any string in double quotes with escapes
    '''
    # For simplicity, always quote and escape
    s = str(s)
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    return f'"{s}"'


def escape_html_label(s):
    '''Escape a string for use in HTML-like labels'''
    return html.escape(str(s))


def get_node_label(node_id, node_obj, bases, show_full_iri=False):
    '''
    Generate a display label for a node

    Args:
        node_id: The node's IRI
        node_obj: The node object
        bases: List of base IRIs for abbreviation
        show_full_iri: If True, show full IRI; if False, abbreviate

    Returns:
        String label for the node
    '''
    if show_full_iri:
        return str(node_id)
    else:
        return abbreviate(node_id, bases)


def get_node_shape(node_obj, type_shapes):
    '''
    Determine the shape for a node based on its types

    Args:
        node_obj: The node object
        type_shapes: Dict mapping type IRIs to shape names

    Returns:
        Shape name (default: 'box')
    '''
    if not type_shapes or not node_obj.types:
        return 'box'

    # Return shape for first matching type
    for node_type in node_obj.types:
        if node_type in type_shapes:
            return type_shapes[node_type]

    return 'box'


def get_node_color(node_obj, type_colors):
    '''
    Determine the color for a node based on its types

    Args:
        node_obj: The node object
        type_colors: Dict mapping type IRIs to color names

    Returns:
        Color name or None
    '''
    if not type_colors or not node_obj.types:
        return None

    # Return color for first matching type
    for node_type in node_obj.types:
        if node_type in type_colors:
            return type_colors[node_type]

    return None


def format_properties_html(properties, bases):
    '''
    Format properties as an HTML table for display in node label

    Args:
        properties: List of (label, value) tuples
        bases: List of base IRIs for abbreviation

    Returns:
        HTML string for table
    '''
    if not properties:
        return ''

    rows = []
    for label, value in properties:
        abbr_label = abbreviate(label, bases)
        # Truncate very long values
        display_value = str(value)
        if len(display_value) > 50:
            display_value = display_value[:47] + '…'

        escaped_label = escape_html_label(abbr_label)
        escaped_value = escape_html_label(display_value)
        rows.append(f'<tr><td align="left">{escaped_label}:</td><td align="left">{escaped_value}</td></tr>')

    return '<table border="0" cellborder="0" cellspacing="0">' + ''.join(rows) + '</table>'


def write(model, out=sys.stdout,
          base=None,
          propertybase=None,
          rankdir='TB',
          show_properties=True,
          show_types=True,
          show_edge_labels=True,
          show_edge_annotations=True,
          node_shapes=None,
          node_colors=None,
          graph_attrs=None,
          node_attrs=None,
          edge_attrs=None):
    '''
    Serialize an Onya graph to Graphviz DOT format

    Args:
        model: The Onya graph to serialize
        out: File pointer to write to (default: sys.stdout)
        base: Base IRI for abbreviating node IDs
        propertybase: Base IRI for abbreviating property labels
        rankdir: Graph layout direction - 'TB' (top-bottom), 'LR' (left-right),
                 'BT' (bottom-top), 'RL' (right-left)
        show_properties: If True, show node properties as HTML table in node
        show_types: If True, show node types in the node display
        show_edge_labels: If True, show edge labels
        show_edge_annotations: If True, show annotations on edges
        node_shapes: Dict mapping type IRIs to Graphviz shape names
                     (e.g., {'http://schema.org/Person': 'ellipse'})
        node_colors: Dict mapping type IRIs to color names
                     (e.g., {'http://schema.org/Person': 'lightblue'})
        graph_attrs: Dict of additional graph-level attributes
        node_attrs: Dict of default node attributes
        edge_attrs: Dict of default edge attributes

    Common Graphviz shapes: box, ellipse, circle, diamond, plaintext, rectangle
    Common colors: lightblue, lightgreen, lightyellow, lightgray, white
    '''
    node_shapes = node_shapes or {}
    node_colors = node_colors or {}
    graph_attrs = graph_attrs or {}
    node_attrs = node_attrs or {}
    edge_attrs = edge_attrs or {}

    all_propertybase = [propertybase] if propertybase else []
    all_propertybase.append(ONYA_BASEIRI)

    all_base = [base] if base else []

    # Write DOT header
    out.write('digraph G {\n')

    # Graph attributes
    out.write(f'  rankdir={rankdir};\n')
    out.write('  node [fontname="Arial", fontsize=10];\n')
    out.write('  edge [fontname="Arial", fontsize=9];\n')

    for key, value in graph_attrs.items():
        out.write(f'  {key}={escape_dot_id(value)};\n')

    # Default node attributes
    if node_attrs:
        attrs_str = ', '.join(f'{k}={escape_dot_id(v)}' for k, v in node_attrs.items())
        out.write(f'  node [{attrs_str}];\n')

    # Default edge attributes
    if edge_attrs:
        attrs_str = ', '.join(f'{k}={escape_dot_id(v)}' for k, v in edge_attrs.items())
        out.write(f'  edge [{attrs_str}];\n')

    out.write('\n')

    # Collect all nodes and their properties/edges
    # We'll make two passes: one for nodes, one for edges
    origin_space = set(model.keys()) if hasattr(model, 'keys') else set()

    # Pass 1: Define all nodes
    for node_id in origin_space:
        node_obj = model[node_id]

        # Collect properties for this node
        node_properties = []
        node_edges = []

        for origin, relation, target, annotations in model.match(node_id):
            # Check if target is a node ID (edge) or a literal value (property)
            # Edges point to node IDs that exist in the model
            if target in origin_space:
                # It's an edge (target is a node ID)
                node_edges.append((relation, target, annotations))
            else:
                # It's a property (target is a literal string value)
                node_properties.append((relation, target))

        # Build node label
        label_parts = []

        # Add abbreviated node ID
        display_id = get_node_label(node_id, node_obj, all_base)
        label_parts.append(f'<b>{escape_html_label(display_id)}</b>')

        # Add types if requested
        if show_types and node_obj.types:
            types_str = ', '.join(abbreviate(t, all_propertybase) for t in node_obj.types)
            label_parts.append(f'<font point-size="8">[{escape_html_label(types_str)}]</font>')

        # Add properties if requested
        if show_properties and node_properties:
            props_html = format_properties_html(node_properties, all_propertybase)
            label_parts.append(props_html)

        # Combine label parts
        if len(label_parts) > 1:
            # Use HTML-like label
            label_html = '<br/>'.join(label_parts)
            label_attr = f'label=<{label_html}>'
        else:
            # Simple text label
            label_attr = f'label=<{label_parts[0]}>'

        # Determine node shape and color
        shape = get_node_shape(node_obj, node_shapes)
        color = get_node_color(node_obj, node_colors)

        # Write node definition
        node_id_esc = escape_dot_id(node_id)
        attrs = [label_attr, f'shape={shape}']
        if color:
            attrs.append(f'fillcolor={color}')
            attrs.append('style=filled')

        out.write(f'  {node_id_esc} [{", ".join(attrs)}];\n')

    out.write('\n')

    # Pass 2: Define all edges
    for node_id in origin_space:
        for origin, relation, target, annotations in model.match(node_id):
            # Only process edges (target is a node ID that exists in the model)
            if target in origin_space:
                source_esc = escape_dot_id(origin)
                target_esc = escape_dot_id(target)

                edge_attrs_list = []

                # Add edge label if requested
                if show_edge_labels:
                    edge_label = abbreviate(relation, all_propertybase)

                    # Add annotations to label if requested
                    if show_edge_annotations and annotations:
                        annotation_parts = [edge_label]
                        for ann_key, ann_value in annotations.items():
                            ann_key_abbr = abbreviate(ann_key, all_propertybase)
                            # Truncate long annotation values
                            ann_value_str = str(ann_value)
                            if len(ann_value_str) > 30:
                                ann_value_str = ann_value_str[:27] + '…'
                            annotation_parts.append(f'{ann_key_abbr}={ann_value_str}')
                        edge_label = '\\n'.join(annotation_parts)

                    edge_attrs_list.append(f'label={escape_dot_id(edge_label)}')

                # Write edge
                if edge_attrs_list:
                    out.write(f'  {source_esc} -> {target_esc} [{", ".join(edge_attrs_list)}];\n')
                else:
                    out.write(f'  {source_esc} -> {target_esc};\n')

    # Close graph
    out.write('}\n')
