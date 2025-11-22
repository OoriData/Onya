**Onya** is a knowledge graph expression and implementation. This repository combines a [data model and format spec](SPEC.md) with a Python parser and API implementation.

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

## Basic Usage

Here's a simple example demonstrating the core Onya API. First, let's define a small friendship graph in Onya Literate format:

```
# @docheader

* @document: http://example.org/friendship-graph
* @base: http://example.org/people/
* @schema: https://schema.org/
* @type-base: https://schema.org/

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
from onya.serial import literate_lex

# Parse the Onya Literate text into a graph
onya_text = '''
# @docheader

* @document: http://example.org/friendship-graph
* @base: http://example.org/people/
* @schema: https://schema.org/
* @type-base: https://schema.org/

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
doc_iri = literate_lex.parse(onya_text, g)
print(f"Parsed document: {doc_iri}")
print(f"Graph has {len(g)} nodes")

# Access nodes and their properties
chuks = g['http://example.org/people/Chuks']
ify = g['http://example.org/people/Ify']

# Get a specific property value
for prop in chuks.getprop('https://schema.org/name'):
    print(f"Name: {prop.value}")

# Add a friendship edge between Chuks and Ify
friendship = chuks.add_edge('https://schema.org/knows', ify)
print(f"Added edge: {friendship}")

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
        print(f"Chuks knows: {name_prop.value}")
    # Access nested properties on the edge
    for date_prop in edge.getprop('https://schema.org/startDate'):
        print(f"  Friends since: {date_prop.value}")

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

# Acknowledgments

<table><tr>
  <td><a href="https://oori.dev/"><img src="https://www.oori.dev/assets/branding/oori_Logo_FullColor.png" width="64" /></a></td>
  <td>Onya is primarily developed by the crew at <a href="https://oori.dev/">Oori Data</a>. We offer LLMOps, data pipelines and software engineering services around AI/LLM applications.</td>
</tr></table>

# Background

Onya is based on experience from developing [Versa](https://github.com/uogbuji/versa) and also working on [the MicroXML spec](https://dvcs.w3.org/hg/microxml/raw-file/tip/spec/microxml.html) and implementations thereof.

The URL used for metavocabulary is [managed via purl.org](https://purl.archive.org/purl/onya/vocab).

The name is from Igbo "ọ́nyà", web, snare, trap, and by extension, network. The expanded sense is ọ́nyà úchè, web of knowledge.

# Contributing

Contributions welcome! We're interested in feedback from the community about what works and what doesn't in real-world usage. To get help with the code implementation, read [CONTRIBUTING.md](CONTRIBUTING.md).

# License

- **Code** (Python library): Apache 2.0 - See [LICENSE](LICENSE)
- **Specification** (wordloom_spec.md): [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) - See [LICENSE-spec](LICENSE-spec)

The specification is under CC BY 4.0 to encourage broad adoption and derivative work while ensuring attribution. We want the format itself to be as open and reusable as possible, allowing anyone to create implementations in any language or adapt the format for their specific needs.

# Related Work

- [networkx](https://github.com/networkx/networkx): Network Analysis in Python
- [Apache AGE](https://github.com/apache/incubator-age): PostgreSQL Extension that for graphs. ANSI SQL & openCypher over the same DB.
