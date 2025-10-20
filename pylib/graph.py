'''
Graph and other fundamental classes for Onya
'''

from __future__ import annotations
from collections.abc import MutableMapping, Iterator
from typing import Any

from amara.iri import I


class properties_mixin:
    def add_property(self, label, value):
        p = property_(self, label, value)
        self.properties.add(p)
        return p

    def remove_property(self, prop):
        self.properties.remove(prop)

    def getprop(self, label):
        for prop in self.properties:
            if prop.label == label:
                yield prop


class node(properties_mixin):
    '''
    Basic unit of information in onya is a node. A node, also called
    a vertex in graph theory, comprises an identifier (an IRI),
    a sequence of properties and a sequence of edges.
    '''
    __slots__ = ['id', 'types', 'properties', 'edges']

    # XXX Design decision: don't have containing graph as a property. Removes circularity that might not be needed. Keeps open popularity of node reuse across graphs.
    def __init__(self, id_: I | str, types: str | list[str] | None = None):
        self.id = id_
        # self.graph = graph_
        if isinstance(types, str):
            types = [types]
        self.types: set[str] = set(types) if types else set()
        self.properties: set[property_] = set()
        self.edges: set[edge] = set()
    
    def add_edge(self, label: I | str, target: node) -> edge:
        e = edge(self, label, target)
        self.edges.add(e)
        return e

    def remove_edge(self, edge_: edge) -> None:
        self.edges.remove(edge_)

    def traverse(self, label: I | str) -> Iterator[edge]:
        for e in self.edges:
            if e.label == label:
                yield e

    def reverse(self, label: I | str) -> Iterator[edge]:
        # Note: This method requires access to the containing graph
        # which we don't have in the current design
        for nid, nobj in self.graph.nodes.items():
            for e in nobj.traverse(label):
                if e.target == self:
                    yield e


class property_(properties_mixin):
    '''
    Means of imparting a value to a node
    '''
    __slots__ = ['origin', 'label', 'value', 'properties']

    def __init__(self, origin: node | property_ | edge, label: I | str, value: Any):
        self.origin = origin
        self.label = label
        self.value = value
        self.properties: set[property_] = set()

    def add_property(self, label, value):
        p = property_(self, label, value)
        self.properties.add(p)

    def remove_property(self, prop):
        self.properties.remove(prop)

    def getprop(self, label):
        for prop in self.properties:
            if prop.label == label:
                yield prop


class edge(properties_mixin):
    '''
    Directional relationship between one node and another
    '''
    __slots__ = ['origin', 'label', 'target', 'properties']

    def __init__(self, origin: node, label: I | str, target: node):
        self.origin = origin
        self.label = label
        self.target = target
        self.properties: set[property_] = set()

    def add_property(self, label, value):
        p = property_(self, label, value)
        self.properties.add(p)

    def remove_property(self, prop):
        self.properties.remove(prop)

    def getprop(self, label):
        for prop in self.properties:
            if prop.label == label:
                yield prop


class graph(MutableMapping):
    '''
    Collection of nodes managed and queried together
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

    def node(self, nid: I | str, types: str | list[str] | None = None, node_: type[node] = node) -> node:
        '''
        Convenience for constructing, then adding a new node to the graph
        '''
        n = node_(nid, types)
        self[nid] = n
        return n

    def typematch(self, types: set[str] | list[str]) -> Iterator[node]:
        types_set = set(types)
        for n in self.nodes.values():
            if n.types & types_set:
                yield n
