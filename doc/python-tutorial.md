# Python quick start

[![PyPI - Version](https://img.shields.io/pypi/v/onya.svg)](https://pypi.org/project/Onya)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/onya.svg)](https://pypi.org/project/Onya)

## Installation

<!--
```bash
pip install amara
```

Or with uv (recommended):

```bash
uv pip install amara
```
-->

Requires Python 3.12 or later. The package is still in early development, so install directly from source:

```bash
git clone https://github.com/OoriData/Onya.git
cd Onya
pip install -U .
```

<!--
pip install git+https://github.com/OoriData/Onya.git
-->

## Command line tool

You can use the built-in CLI to export directly from an Onya Literate (`.onya`) file to the Mermaid diagram format:

```sh
onya convert test/resource/schemaorg/thingsfallapart.onya > out.mmd
```

Then use a site such as https://mermaid.live/ to generate a diagram such as:

![Running MLX-LM generate within Python](test/resource/schemaorg/thingsfallapart.png)

## Basic Python Usage

Here's a simple example demonstrating the core Onya API. First, let's define a small friendship graph in Onya Literate format:

```
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor
* nickname: Chuks
* age: 28

# Ify [Person]

* name: Ifeoma Obasi
* nickname: Ify
* age: 27
```

Parse this graph and interact with it using the Python API.

```python
from onya.graph import graph
from onya.serial.literate import LiterateParser

# Parse the Onya Literate text into a graph
onya_text = '''
# @docheader

* @document: http://example.org/friendship-graph
* @nodebase: http://example.org/people/
* @schema: https://schema.org/

# Chuks [Person]

* name: Chukwuemeka Okafor
* nickname: Chuks
* age: 28

# Ify [Person]

* name: Ifeoma Obasi
* nickname: Ify
* age: 27
'''

g = graph()
op = LiterateParser()
result = op.parse(onya_text, g)
doc_iri = result.doc_iri
print(f'Parsed document: {doc_iri}')
print(f'Graph has {len(g)} nodes')

# Access nodes and their properties
chuks = g['http://example.org/people/Chuks']
ify = g['http://example.org/people/Ify']

# Get a specific property value
for prop in chuks.getprop('https://schema.org/name'):
    print(f'Name: {prop.value}')

# Add a friendship edge between Chuks and Ify
friendship = chuks.add_edge('https://schema.org/knows', ify)
print(f'Added edge: {friendship}')

# Add nested properties to the friendship (metadata about the relationship)
friendship.add_property('https://schema.org/startDate', '2018-03-15')
friendship.add_property('https://schema.org/description', 'Met at university')

# Add a new property to Ify
ify.add_property('https://schema.org/jobTitle', 'Software Engineer')

# Modify a property by removing the old one and adding a new one
age_props = list(chuks.getprop('https://schema.org/age'))
for prop in age_props:
    chuks.remove_property(prop)
chuks.add_property('https://schema.org/age', '29')

# Traverse edges
for edge in chuks.traverse('https://schema.org/knows'):
    friend = edge.target
    for name_prop in friend.getprop('https://schema.org/name'):
        print(f'Chuks knows: {name_prop.value}')
    # Access nested properties on the edge
    for date_prop in edge.getprop('https://schema.org/startDate'):
        print(f'  Friends since: {date_prop.value}')

# Find all nodes of a certain type
for person in g.typematch('https://schema.org/Person'):
    for name_prop in person.getprop('https://schema.org/name'):
        print(f'Person in graph: {name_prop.value}')

# Reserialize to Onya literate
from onya.serial.literate import write

write(g)
```

This example demonstrates:
- Parsing Onya Literate format
- Accessing nodes and properties
- Adding edges with nested properties (reified relationships)
- Modifying properties
- Traversing the graph
- Querying by type

# Visualization / export

Onya includes simple serializers to help you visualize graphs:

- **Graphviz (DOT)**: `from onya.serial import graphviz` → `graphviz.write(g, out=f)` (see `demo/graphviz_basic/`)
- **Mermaid (flowchart)**: `from onya.serial import mermaid` → `mermaid.write(g, out=f)` (see `demo/mermaid_basic/`; quick viewing via [Mermaid Live Editor](https://mermaid.live/))

