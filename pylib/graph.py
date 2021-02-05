'''
Graph and other fundamental classes for Onya
'''

from collections.abc import MutableMapping

from amara3.iri import I

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
    __slots__ = ['id', 'class_', 'properties', 'edges'] # , 'graph'

    # XXX Design decision: don't have containing graph as a property. Removes circularity that might not be needed. Keeps open popularity pof node reuse across graphs.
    def __init__(self, id_, types=None):
        self.id = id_
        # self.graph = graph_
        if isinstance(types, str):
            types = [types]
        self.types = set(types) if types else set()
        self.properties = set()
        self.edges = set()
    
    def add_edge(self, label, target):
        e = edge(self, label, target)
        self.edges.add(e)
        return e

    def remove_edge(self, edge_):
        self.properties.remove(edge_)

    def traverse(self, label):
        for e in self.edges:
            if e.label == label:
                yield e

    def reverse(self, label):
        for nid, nobj in self.graph.nodes.items():
            for e in nobj.traverse(label):
                if e.target == self:
                    yield e


class property_(properties_mixin):
    '''
    Means of imparting a value to a node
    '''
    __slots__ = ['origin', 'label', 'value', 'properties']

    def __init__(self, origin, label, value):
        self.origin = origin
        self.label = label
        self.value = value
        self.properties = set()

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

    def __init__(self, origin, label, target):
        self.origin = origin
        self.label = label
        self.target = target
        self.properties = set()

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
    def __init__(self, nodes=()):
        self.nodes = {}
        self.nodes.update({n.id: n for n in nodes})

    def __getitem__(self, key):
        return self.nodes[key]

    def __delitem__(self, nid):
        del self.nodes[nid]

    def __setitem__(self, nid, nobj):
        self.nodes[nid] = nobj

    def __iter__(self):
        return iter(self.nodes)

    def __len__(self):
        return len(self.nodes)

    def __repr__(self):
        return f"{type(self).__name__} with {len(self.nodes)} nodes"

    def node(self, nid, types=None, node_=node):
        '''
        Convenience for contructing, then adding a new node to the graph
        '''
        n = node_(nid, types)
        self[nid] = n
        return n

    def typematch(self, types):
        types = set(types)
        for n in self.nodes:
            if n.types & types:
                yield n
