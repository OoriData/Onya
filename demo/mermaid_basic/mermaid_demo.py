#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# demo/mermaid_basic/mermaid_demo.py

'''
Demo script showing how to use the Onya Mermaid emitter.

Usage:
    python mermaid_demo.py

This will generate several .mmd files containing Mermaid markup. You can:
- paste the contents into Mermaid Live Editor, or
- embed in Markdown using a ```mermaid code fence (GitHub, many docs sites, etc.)

Mermaid reference: https://mermaid.js.org/intro/syntax-reference.html
'''

from pathlib import Path

from onya.graph import graph
from onya.serial import mermaid
from onya.serial.literate_lex import LiterateParser


def demo_basic():
    '''Basic graph with nodes, properties, and edges'''
    print('Creating basic graph…')

    g = graph()

    # Create people
    chuks = g.node('http://example.org/people/Chuks', 'http://schema.org/Person')
    ify = g.node('http://example.org/people/Ify', 'http://schema.org/Person')
    ada = g.node('http://example.org/people/Ada', 'http://schema.org/Person')

    # Add properties
    chuks.add_property('http://schema.org/name', 'Chukwuemeka Okafor')
    chuks.add_property('http://schema.org/birthDate', '1985-03-15')
    chuks.add_property('http://schema.org/jobTitle', 'Software Engineer')

    ify.add_property('http://schema.org/name', 'Ifeoma Eze')
    ify.add_property('http://schema.org/birthDate', '1990-07-22')
    ify.add_property('http://schema.org/jobTitle', 'Data Scientist')

    ada.add_property('http://schema.org/name', 'Ada Nwankwo')
    ada.add_property('http://schema.org/birthDate', '1988-11-05')
    ada.add_property('http://schema.org/jobTitle', 'Product Manager')

    # Add relationships
    chuks.add_edge('http://schema.org/knows', ify)
    ify.add_edge('http://schema.org/knows', ada)
    ada.add_edge('http://schema.org/knows', chuks)

    outpath = 'demo_basic.mmd'
    with open(outpath, 'w', encoding='utf-8') as f:
        mermaid.write(g, out=f,
                      base='http://example.org/',
                      propertybase='http://schema.org/')

    print(f'  Generated: {outpath}')
    print('  View by pasting into Mermaid Live Editor, or embedding with ```mermaid\n')


def demo_styled():
    '''
    Graph with basic styling via node shapes (Mermaid styles/colors are not emitted yet).
    '''
    print('Creating shape-styled graph…')

    g = graph()

    # Create different types of entities
    book = g.node('http://example.org/books/TFA', 'http://schema.org/Book')
    author = g.node('http://example.org/people/Achebe', 'http://schema.org/Person')
    publisher = g.node('http://example.org/orgs/Heinemann', 'http://schema.org/Organization')
    place = g.node('http://example.org/places/London', 'http://schema.org/Place')

    # Add properties
    book.add_property('http://schema.org/name', 'Things Fall Apart')
    book.add_property('http://schema.org/isbn', '9781841593272')
    book.add_property('http://schema.org/datePublished', '1958')

    author.add_property('http://schema.org/name', 'Chinua Achebe')
    author.add_property('http://schema.org/birthDate', '1930-11-16')

    publisher.add_property('http://schema.org/name', 'William Heinemann Ltd.')
    place.add_property('http://schema.org/name', 'London')

    # Add relationships
    book.add_edge('http://schema.org/author', author)
    book.add_edge('http://schema.org/publisher', publisher)
    publisher.add_edge('http://schema.org/location', place)

    outpath = 'demo_styled.mmd'
    with open(outpath, 'w', encoding='utf-8') as f:
        mermaid.write(g, out=f,
                      base='http://example.org/',
                      propertybase='http://schema.org/',
                      rankdir='LR',
                      node_shapes={
                          'http://schema.org/Person': 'round',
                          'http://schema.org/Place': 'diamond',
                          'http://schema.org/Book': 'box',
                          'http://schema.org/Organization': 'box',
                      })

    print(f'  Generated: {outpath}')
    print('  (Note: this demo uses shapes only; Mermaid styling directives are a future enhancement)\n')


def demo_reified():
    '''Graph with reified relationships (edges with properties)'''
    print('Creating graph with reified relationships…')

    g = graph()

    alice = g.node('http://example.org/Alice', 'http://schema.org/Person')
    bob = g.node('http://example.org/Bob', 'http://schema.org/Person')
    carol = g.node('http://example.org/Carol', 'http://schema.org/Person')

    alice.add_property('http://schema.org/name', 'Alice Johnson')
    bob.add_property('http://schema.org/name', 'Bob Smith')
    carol.add_property('http://schema.org/name', 'Carol Williams')

    friendship1 = alice.add_edge('http://schema.org/knows', bob)
    friendship1.add_property('http://schema.org/startDate', '2018-03-15')
    friendship1.add_property('http://schema.org/description', 'Met at conference')

    friendship2 = bob.add_edge('http://schema.org/knows', carol)
    friendship2.add_property('http://schema.org/startDate', '2020-06-01')
    friendship2.add_property('http://schema.org/description', 'College roommates')

    outpath = 'demo_reified.mmd'
    with open(outpath, 'w', encoding='utf-8') as f:
        mermaid.write(g, out=f,
                      base='http://example.org/',
                      propertybase='http://schema.org/',
                      show_edge_annotations=True,
                      node_shapes={'http://schema.org/Person': 'round'})

    print(f'  Generated: {outpath}\n')


def demo_minimal():
    '''Minimal graph showing only structure without properties'''
    print('Creating minimal graph (structure only)…')

    g = graph()

    animal = g.node('http://example.org/Animal', 'http://www.w3.org/2002/07/owl#Class')
    mammal = g.node('http://example.org/Mammal', 'http://www.w3.org/2002/07/owl#Class')
    bird = g.node('http://example.org/Bird', 'http://www.w3.org/2002/07/owl#Class')
    dog = g.node('http://example.org/Dog', 'http://www.w3.org/2002/07/owl#Class')
    cat = g.node('http://example.org/Cat', 'http://www.w3.org/2002/07/owl#Class')

    mammal.add_edge('http://www.w3.org/2000/01/rdf-schema#subClassOf', animal)
    bird.add_edge('http://www.w3.org/2000/01/rdf-schema#subClassOf', animal)
    dog.add_edge('http://www.w3.org/2000/01/rdf-schema#subClassOf', mammal)
    cat.add_edge('http://www.w3.org/2000/01/rdf-schema#subClassOf', mammal)

    outpath = 'demo_minimal.mmd'
    with open(outpath, 'w', encoding='utf-8') as f:
        mermaid.write(g, out=f,
                      base='http://example.org/',
                      propertybase='http://www.w3.org/2000/01/rdf-schema#',
                      show_properties=False,
                      show_types=False,
                      rankdir='BT')

    print(f'  Generated: {outpath}\n')


def demo_from_literate():
    '''Parse an Onya Literate document and export to Mermaid markup'''
    print('Parsing an Onya Literate document and exporting to Mermaid…')

    root = Path(__file__).resolve().parents[2]
    docpath = root / 'test' / 'resource' / 'schemaorg' / 'thingsfallapart.onya'

    g = graph()
    op = LiterateParser()
    result = op.parse(docpath.read_text(encoding='utf-8'), g)

    outpath = 'demo_literate.mmd'
    with open(outpath, 'w', encoding='utf-8') as f:
        mermaid.write(g, out=f,
                      base='http://example.org/',
                      propertybase='https://schema.org/')

    print(f'  Parsed: {docpath.name} (@document={result.doc_iri})')
    print(f'  Generated: {outpath}\n')


def main():
    print('Onya Mermaid Emitter Demo')
    print('=' * 50)
    print()

    demo_basic()
    demo_styled()
    demo_reified()
    demo_minimal()
    demo_from_literate()

    print('=' * 50)
    print('All demos complete!')
    print()
    print('Cleanup:')
    print('  rm -f demo_*.mmd')


if __name__ == '__main__':
    main()

