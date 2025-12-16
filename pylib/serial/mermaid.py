# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# onya.serial.mermaid

'''
Serialize an Onya model to Mermaid flowchart markup.

This serializer **only outputs Mermaid syntax**; it does not render diagrams.

Example usage:
    from io import StringIO
    from onya.graph import graph
    from onya.serial import mermaid

    g = graph()
    alice = g.node('http://example.org/Alice', 'http://schema.org/Person')
    bob = g.node('http://example.org/Bob', 'http://schema.org/Person')
    alice.add_edge('http://schema.org/knows', bob)

    out = StringIO()
    mermaid.write(g, out=out, rankdir='LR')
    print(out.getvalue())

See: https://mermaid.js.org/intro/syntax-reference.html

You can quickly view Mermaid diagrams in your browser by pasting the output
into an online editor like https://mermaid.live/
'''

from __future__ import annotations

import sys

from onya.util import abbreviate, ONYA_BASEIRI

__all__ = ['write']


def _escape_mermaid_string(s: object) -> str:
    '''
    Escape text for inclusion inside Mermaid double quotes.

    Mermaid flowchart labels can contain HTML-ish `<br/>` for line breaks in many renderers.
    '''
    s = str(s)
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    # Prefer <br/> over literal newlines for portability across renderers.
    s = s.replace('\n', '<br/>')
    return s


def _node_def(node_mermaid_id: str, label: str, shape: str) -> str:
    '''
    Build a Mermaid node definition with a chosen shape.

    Shapes are expressed using Mermaid's bracket/paren syntax:
    - box:     A[label]
    - round:   A(label)
    - circle:  A((label))
    - diamond: A{label}
    '''
    label_q = f'"{_escape_mermaid_string(label)}"'
    shape = (shape or 'box').lower()

    if shape in ('round', 'rounded', 'ellipse'):
        return f'{node_mermaid_id}({label_q})'
    if shape in ('circle',):
        return f'{node_mermaid_id}(({label_q}))'
    if shape in ('diamond',):
        return f'{node_mermaid_id}{{{label_q}}}'

    # Default: rectangular/box.
    return f'{node_mermaid_id}[{label_q}]'


def _get_node_shape(node_obj, type_shapes: dict) -> str:
    if not type_shapes or not getattr(node_obj, 'types', None):
        return 'box'
    for t in node_obj.types:
        if t in type_shapes:
            return type_shapes[t]
    return 'box'


def write(model, out=sys.stdout,
          base=None,
          propertybase=None,
          rankdir='TB',
          show_properties=True,
          show_types=True,
          show_edge_labels=True,
          show_edge_annotations=True,
          node_shapes=None):
    '''
    Serialize an Onya graph to Mermaid flowchart syntax.

    Args:
        model: The Onya graph to serialize
        out: File pointer to write to (default: sys.stdout)
        base: Base IRI for abbreviating node display labels
        propertybase: Base IRI for abbreviating property and edge labels
        rankdir: Flow direction - 'TB' (top-bottom), 'LR' (left-right),
                 'BT' (bottom-top), 'RL' (right-left)
        show_properties: If True, include node properties in labels
        show_types: If True, include node types in labels
        show_edge_labels: If True, include edge labels
        show_edge_annotations: If True, include edge annotations in edge labels
        node_shapes: Dict mapping type IRIs to a Mermaid-ish shape name
                     ('box', 'round', 'circle', 'diamond'). Unknown values fall back to box.
    '''
    node_shapes = node_shapes or {}

    all_propertybase = [propertybase] if propertybase else []
    all_propertybase.append(ONYA_BASEIRI)

    all_base = [base] if base else []

    # Mermaid header
    rankdir = (rankdir or 'TB').upper()
    if rankdir not in ('TB', 'LR', 'BT', 'RL'):
        rankdir = 'TB'
    out.write(f'flowchart {rankdir}\n')

    # Collect all nodes
    origin_space = set(model.keys()) if hasattr(model, 'keys') else set(model)
    ordered_node_ids = sorted(origin_space, key=lambda x: str(x))

    # Stable Mermaid node IDs: n0, n1, ...
    mermaid_ids: dict[object, str] = {nid: f'n{i}' for i, nid in enumerate(ordered_node_ids)}

    # Pass 1: node definitions (with labels)
    for node_id in ordered_node_ids:
        node_obj = model[node_id]

        node_properties: list[tuple[object, object]] = []

        for origin, relation, target, _annotations in model.match(node_id):
            if target in origin_space:
                continue
            node_properties.append((relation, target))

        # Build label lines
        label_lines: list[str] = []
        display_id = abbreviate(node_id, all_base) if all_base else str(node_id)
        label_lines.append(display_id)

        if show_types and getattr(node_obj, 'types', None):
            types_str = ', '.join(abbreviate(t, all_propertybase) for t in node_obj.types)
            label_lines.append(f'[{types_str}]')

        if show_properties and node_properties:
            for rel, val in node_properties:
                rel_abbr = abbreviate(rel, all_propertybase)
                val_str = str(val)
                if len(val_str) > 50:
                    val_str = val_str[:47] + '…'
                label_lines.append(f'{rel_abbr}: {val_str}')

        label = '<br/>'.join(label_lines)
        shape = _get_node_shape(node_obj, node_shapes)

        out.write(f'  {_node_def(mermaid_ids[node_id], label, shape)}\n')

    out.write('\n')

    # Pass 2: edges
    for node_id in ordered_node_ids:
        for origin, relation, target, annotations in model.match(node_id):
            if target not in origin_space:
                continue

            src = mermaid_ids[origin]
            dst = mermaid_ids[target]

            if not show_edge_labels:
                out.write(f'  {src} --> {dst}\n')
                continue

            edge_label = abbreviate(relation, all_propertybase)
            if show_edge_annotations and annotations:
                ann_parts = [edge_label]
                for ann_key, ann_value in annotations.items():
                    ann_key_abbr = abbreviate(ann_key, all_propertybase)
                    ann_value_str = str(ann_value)
                    if len(ann_value_str) > 30:
                        ann_value_str = ann_value_str[:27] + '…'
                    ann_parts.append(f'{ann_key_abbr}={ann_value_str}')
                edge_label = '<br/>'.join(ann_parts)

            edge_label_q = f'"{_escape_mermaid_string(edge_label)}"'
            out.write(f'  {src} -- {edge_label_q} --> {dst}\n')

