Onya Model Specification

# Overview

Onya is a knowledge graph framework with a simple, recursive model for representing structured information. The core model is intentionally minimal—just nodes, edges, and properties, identifiable by IRIs.

# Core Concepts

## Graph

Collection of nodes managed together. Provides the top-level container for the Onya model.

## Node

Fundamental unit of information in Onya. Each node has:

- **id**: An identifier expressed as an IRI
- **types**: A set of IRIs that classify the node
- **assertions**: A set of edges and properties

Nodes use **sets** (not sequences) for assertions because pervasive ordering is not a core requirement of the model. Other layers can add ordering as needed.

## Assertions

Edges and properties are collectively called **assertions**. Each assertion is in effect an anonymous node defined by the combination of:
- its origin (a node or another assertion)
- its label (an IRI)
- an internal marker or tracker to differentiate between other, similar assertions

### Edge

An **edge** connects an origin to a target node via an IRI label.

```
origin --[IRI label]--> target node
```

### Property

A **property** connects an origin to a string value via an IRI label.

```
origin --[IRI label]--> "string value"
```

# Example

A mother can have multiple children. In Onya, each parental relationship can be modeled with an edge from the node representing the mother (the assertion's origin) to the node representing the child (the assertion's target). Each of these edges is a separate, anaonymous node which can have its own assertions, e.g. date of labor (though of course another modeler could choose to model this instead just using a date of birth edge on each child node).

# Notes

## String Properties

Properties in Onya always have string values. There are no numbers, dates, or other types at the core layer. Annotation systems can be built on top to add typing semantics.

## Recursive Structure

A key feature of Onya is that **assertions themselves can be origins for further assertions**. This natural recursiveness means:

- An edge can have properties and edges
- A property can have properties and edges
- There's no separate concept of "attributes" - just recursive assertions

This enables representation of:
- Metadata about relationships (e.g., a marriage with a date and location)
- Qualified values (e.g., a temperature with units and measurement method)
- N-ary relationships (e.g., a sale with buyer, seller, item, and price)

## IRIs Throughout

All identifiers in Onya are IRIs:
- Node IDs
- Node types
- Edge labels
- Property labels

This provides a uniform, standard way to identify and dereference all elements of the graph.

# Onya Literate Serialization

The human-friendly Onya Literate format is based on Markdown, making it easy to read and write knowledge graphs.

### File Structure

An Onya Literate file contains:

1. **Document Header** - metadata about the document itself
2. **Node Blocks** - definitions of nodes and their assertions

## Comments

Comments use HTML comment syntax:

```
<!-- This is a comment -->
```

These are ignored by the parser and do not appear in the graph in any way. They will also be ignored by most markdown processors.

## Document Header

```
# @docheader

* @document: http://example.org/doc
* title: Example Document
* @base: http://example.org/
* @schema: https://schema.org/
* @language: en
```

The document header specifies:
- `@document`: IRI of the document itself
- `@base`: Base IRI for resolving relative node IDs
- `@schema`: Base IRI for schema vocabulary (types, property/edge labels)
- `@language`: Default language for string values
- Other assertions are attached to the document node

## Node Blocks

Each node block defines a node:

```
# NodeID [Type]

* label: value
<!-- Additional assertions -->
```

Structure:
- Header: `# NodeID [OptionalType]`
  - `NodeID` is resolved relative to `@base`
  - `Type` is resolved relative to `@schema`
- Assertions: list items starting with `*`
  - `label: value` - property (label is IRI, value is string)
  - `label -> TargetID` - edge (label is IRI, TargetID is node ID)
- Indentation indicates nested assertions

## Example: Things Fall Apart

```
# @docheader

* @document: http://example.org/classics/things-fall-apart
* title: Things Fall Apart knowledgebase
* @base: http://example.org/classics/
* @schema: https://schema.org/
* @language: en

# TFA [Book]

* name: Things Fall Apart
* alternateName: TFA
* isbn: 9781841593272
* datePublished: 1958-06
* bookFormat -> Paperback
* author -> CAchebe
* publisher -> Heinemann

# CAchebe [Person]

* name: Chinua Achebe
* birthDate: 1930-11-16
* birthPlace -> Ogidi
* jobTitle: Novelist

# Heinemann [Organization]

* name: William Heinemann Ltd.
* foundingDate: 1930
* foundingLocation -> London
  * country -> UK
```

## Recursive Assertions Example

Assertions can have nested assertions:

```
# Boston [City]

* name: Boston
  * stateCode: MA
  * country -> USA

Keys to demonstrate qualified values:
* temperature: 25
  * unit: Celsius
  * measurementMethod -> InfraredThermometer
```

In the second example, the `temperature` property has two nested assertions:
- A property `unit` with value "Celsius"
- An edge `measurementMethod` pointing to an `InfraredThermometer` node

## Explicit IRIs

You can use explicit IRIs with angle brackets:

```
* <https://schema.org/name>: Chinua Achebe
```

## Quoted Values

String values can be explicitly quoted:

```
* name: "Things Fall Apart"
* description: "A novel about pre-colonial Igbo society"
```

Use quotes when values contain special characters or when you want to explicitly mark something as a string.

## Model Summary

```
Graph
  └── Node (identified by IRI)
      ├── types: set[IRI]
      ├── properties: set[Property]
      └── edges: set[Edge]
      
Property (anonymous node: origin + label)
  ├── origin: Node | Property | Edge
  ├── label: IRI
  ├── value: str
  ├── properties: set[Property]
  └── edges: set[Edge]

Edge (anonymous node: origin + label)  
  ├── origin: Node | Property | Edge
  ├── label: IRI
  ├── target: Node
  ├── properties: set[Property]
  └── edges: set[Edge]
```

# Design Principles

1. **Simplicity**: Core model uses only nodes, edges, and properties
2. **IRI-based**: All identifiers are IRIs for global uniqueness
3. **String values only**: Keep the core model simple; add typing in layers above
4. **No pervasive ordering**: Use sets for assertions; ordering can be added when needed
5. **Recursive assertions**: Edges and properties are first-class, can have their own assertions
6. **Graph, not model**: The container is a "graph", elements within use "assertions" terminology

# Relationship to Other Models

Onya is similar to RDF but simpler:
- Similar: IRIs, triples (s-p-o), reification via recursive structure
- Simpler: No literals beyond strings, no blank nodes, uniform treatment of properties/edges
- Different: All assertions are "anonymous nodes", properties are always strings

The recursive assertion model is reminiscent of property graphs but more uniform:
- Similar: Nodes and edges both can have properties
- Different: Properties can also have edges, all via the same mechanism
