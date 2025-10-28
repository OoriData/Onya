'''
Graph and other fundamental classes for Onya

The Onya graph model:
- A graph is a collection of nodes
- Each node has:
  - An identifier (IRI)
  - A set of types (IRIs)
  - A set of assertions (edges and properties)
- Edges connect nodes to nodes via IRI labels
- Properties connect nodes to string values via IRI labels
- Both edges and properties are collectively called "assertions"
- Each assertion is in effect an anonymous node defined by (origin IRI, assertion IRI)
- Assertions can themselves be origins for further assertions (natural recursiveness)
'''

from __future__ import annotations
from collections.abc import MutableMapping, Iterator
from abc import ABC

from amara.iri import I


class assertions_mixin:
    '''
    Mixin for objects that can have assertions (edges and properties)
    '''
    def add_property(self, label: I | str, value: str):
        p = property_(self, label, value)
        self.properties.add(p)
        return p

    def add_edge(self, label: I | str, target: 'node'):
        e = edge(self, label, target)
        self.edges.add(e)
        return e

    def remove_property(self, prop: 'property_'):
        self.properties.remove(prop)

    def remove_edge(self, edge_: 'edge'):
        self.edges.remove(edge_)

    def getprop(self, label: I | str):
        '''Get properties with a given label'''
        for prop in self.properties:
            if prop.label == label:
                yield prop
    
    def getedge(self, label: I | str):
        '''Get edges with a given label'''
        for edge_ in self.edges:
            if edge_.label == label:
                yield edge_


class node(assertions_mixin):
    '''
    A node in the Onya graph.
    
    A node has an identifier (IRI), optional types (IRIs), and assertions
    (edges and properties). Both edges and properties are sets, not sequences,
    because pervasive ordering is not a core requirement of the model.
    '''
    __slots__ = ['id', 'types', 'properties', 'edges']

    def __init__(self, id_: I | str, types: I | str | set[I | str] | None = None):
        self.id = id_
        if isinstance(types, str):
            types = I(types)
        if isinstance(types, I):
            types = {types}
        self.types: set[I | str] = set(types) if types else set()
        self.properties: set['property_'] = set()
        self.edges: set['edge'] = set()
    
    def traverse(self, label: I | str) -> Iterator['edge']:
        '''Find edges with a given label'''
        for e in self.edges:
            if e.label == label:
                yield e

    def reverse(self, label: I | str, graph: 'graph') -> Iterator['edge']:
        '''Find edges targeting this node with a given label (requires graph access)'''
        for nid, nobj in graph.nodes.items():
            for e in nobj.traverse(label):
                if e.target == self:
                    yield e


class assertion(assertions_mixin, ABC):
    '''
    Abstract base class for assertions (edges and properties)
    
    Each assertion is an anonymous node defined by the combination of
    its origin and its label IRI.
    '''
    __slots__ = ['origin', 'label', 'properties', 'edges']
    
    def __init__(self, origin: 'node | assertion', label: I | str):
        self.origin = origin
        self.label = label
        self.properties: set['property_'] = set()
        self.edges: set['edge'] = set()


class property_(assertion):
    '''
    A property assertion connects an origin to a string value via an IRI label.
    
    Properties in Onya are simple: they always have string values.
    No numbers, dates, or other types at the core layer - those can be
    handled by annotation systems built on top.
    '''
    __slots__ = ['value']

    def __init__(self, origin: 'node | assertion', label: I | str, value: str):
        super().__init__(origin, label)
        self.value: str = value
    
    def __repr__(self):
        return f'property_({self.label}={self.value!r})'


class edge(assertion):
    '''
    An edge assertion connects an origin node to a target node via an IRI label.
    '''
    __slots__ = ['target']

    def __init__(self, origin: 'node | assertion', label: I | str, target: 'node'):
        super().__init__(origin, label)
        self.target: 'node' = target
    
    def __repr__(self):
        return f'edge({self.label} -> {self.target.id})'


class graph(MutableMapping):
    '''
    A collection of nodes managed and queried together.
    
    This is the top-level container for an Onya graph.
    '''
    def __init__(self, nodes: list[node] = ()):
        self.nodes: dict[I | str, node] = {}
        self.nodes.update({n.id: n for n in nodes})

    def __getitem__(self, key: I | str) -> node:
        return self.nodes[key]

    def __delitem__(self, nid: I | str) -> None:
        del self.nodes[nid]

    def __setitem__(self, nid: I | str, nobj: node) -> None:
        self.nodes[nid] = nobj

    def __iter__(self) -> Iterator[I | str]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        return f'{type(self).__name__} with {len(self.nodes)} nodes'

    def node(self, nid: I | str, types: I | str | set[I | str] | None = None) -> node:
        '''
        Convenience for constructing, then adding a new node to the graph
        '''
        n = node(nid, types)
        self[nid] = n
        return n

    def typematch(self, types: I | str | set[I | str]) -> Iterator[node]:
        '''Find nodes with matching types'''
        if isinstance(types, (str, I)):
            types = {types}
        types_set = set(types)
        for n in self.nodes.values():
            if n.types & types_set:
                yield n
