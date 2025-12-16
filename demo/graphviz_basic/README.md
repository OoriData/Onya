**Onya Graphviz Demo**

This directory contains demo scripts showing how to use the Onya Graphviz emitter.

# Running the Demo

```bash
python graphviz_demo.py
```

This will generate four DOT files demonstrating different features:

1. **demo_basic.dot** - Basic graph with people nodes, properties, and relationships
2. **demo_styled.dot** - Custom styling with different shapes/colors per node type
3. **demo_reified.dot** - Reified relationships (edges with properties/metadata)
4. **demo_minimal.dot** - Minimal structure-only view (no properties displayed)
5. **demo_literate.dot** - Parse an Onya Literate document and export to DOT

# Rendering DOT Files

You need [Graphviz](https://graphviz.org/) installed to render the DOT files to images.

## Install Graphviz

### macOS
```bash
brew install graphviz
```

or if you don't use Homebrew or MacPorts:

[Download and unpack the latest zlib](https://github.com/madler/zlib/releases), then build:

```sh
./configure
make
sudo make install  # If you don't have sudo permission you can use a --prefix with configure
```

- Ditto [libpng](https://www.libpng.org/pub/png/libpng.html)
- Ditto [libpng](https://sourceforge.net/projects/libpng/)
- Ditto [libgd](https://github.com/libgd/libgd/releases/)

Except that for libgd you want to use something like:

- Ditto [graphviz](https://graphviz.org/download/source/)

```sh
./configure --with-png=/usr/local/ --with-zlib=/usr/local/
```

Except that for libgd you want to use something like:

```sh
./configure 
```

### Ubuntu/Debian
```bash
sudo apt-get install graphviz
```

### Windows

Download from https://graphviz.org/download/

## Render to Images

```bash
# PNG format
dot -Tpng demo/demo_basic.dot -o demo/demo_basic.png

# SVG format (scalable, recommended for web)
dot -Tsvg demo/demo_styled.dot -o demo/demo_styled.svg

# PDF format
dot -Tpdf demo/demo_reified.dot -o demo/demo_reified.pdf
```

## Alternative Layout Engines

Graphviz provides different layout engines for different graph types:

- **dot** - Hierarchical/directed graphs (default)
- **neato** - Spring model layout (undirected graphs)
- **fdp** - Force-directed placement (undirected graphs)
- **circo** - Circular layout
- **twopi** - Radial layout
- **sfdp** - Scalable force-directed placement (large graphs)

Example:
```bash
neato -Tpng demo/demo_basic.dot -o demo/demo_basic_neato.png
circo -Tsvg demo/demo_minimal.dot -o demo/demo_minimal_circo.svg
```

# Features Demonstrated

## Basic Graph (demo_basic.dot)
- Creating nodes with types
- Adding properties to nodes
- Creating edges between nodes
- IRI abbreviation for readability

## Styled Graph (demo_styled.dot)
- Custom node shapes based on type (ellipse, box, diamond, note)
- Custom node colors based on type
- Left-to-right layout (`rankdir='LR'`)
- Different entity types (Person, Book, Organization, Place)

## Reified Relationships (demo_reified.dot)
- Edges with properties (metadata on relationships)
- Showing annotations on edge labels
- Use case: friendship with start date and description

## Minimal Graph (demo_minimal.dot)
- Structure-only view (properties hidden)
- Types hidden
- Bottom-to-top layout for taxonomies
- Use case: class hierarchies, ontologies

# Using in Your Code

```python
from onya.graph import graph
from onya.serial import graphviz

# Create and populate graph
g = graph()
node1 = g.node('http://example.org/Node1', 'http://schema.org/Thing')
node1.add_property('http://schema.org/name', 'Example')

# Export to DOT
with open('output.dot', 'w') as f:
    graphviz.write(g, out=f,
                   base='http://example.org/',
                   propertybase='http://schema.org/',
                   rankdir='LR',
                   show_properties=True)
```

# Configuration Options

The `graphviz.write()` function accepts many options:

- **base** - Base IRI for abbreviating node IDs
- **propertybase** - Base IRI for abbreviating property labels
- **rankdir** - Layout direction: 'TB', 'LR', 'BT', 'RL'
- **show_properties** - Show node properties (default: True)
- **show_types** - Show node types (default: True)
- **show_edge_labels** - Show edge labels (default: True)
- **show_edge_annotations** - Show metadata on edges (default: True)
- **node_shapes** - Dict mapping type IRIs to shape names
- **node_colors** - Dict mapping type IRIs to color names
- **graph_attrs** - Additional graph-level DOT attributes
- **node_attrs** - Default node attributes
- **edge_attrs** - Default edge attributes

See `pylib/serial/graphviz.py` for complete documentation.
