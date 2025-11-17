# -*- coding: utf-8 -*-
# test_readme.py
'''
Test the example from the README to ensure it works correctly

pytest -s test/test_readme.py
'''

from onya.graph import graph
from onya.serial import literate_lex


def test_readme_example():
    '''Test the Chuks and Ify friendship example from the README'''

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

* name: Ifeoma Adebayo
* nickname: Ify
* age: 27
'''

    g = graph()
    doc_iri = literate_lex.parse(onya_text, g)

    # Verify document was parsed
    assert doc_iri == 'http://example.org/friendship-graph'
    assert len(g) == 2  # 2 person nodes (Chuks and Ify)

    # Access nodes and their properties
    chuks = g['http://example.org/people/Chuks']
    ify = g['http://example.org/people/Ify']

    # Verify node types
    assert 'https://schema.org/Person' in chuks.types
    assert 'https://schema.org/Person' in ify.types

    # Get a specific property value
    chuks_name = None
    for prop in chuks.getprop('https://schema.org/name'):
        chuks_name = prop.value
    assert chuks_name == 'Chukwuemeka Okafor'

    # Verify nickname
    chuks_nickname = None
    for prop in chuks.getprop('https://schema.org/nickname'):
        chuks_nickname = prop.value
    assert chuks_nickname == 'Chuks'

    # Add a friendship edge between Chuks and Ify
    friendship = chuks.add_edge('https://schema.org/knows', ify)
    assert friendship is not None
    assert friendship.target == ify

    # Add nested properties to the friendship (metadata about the relationship)
    start_date_prop = friendship.add_property('https://schema.org/startDate', '2018-03-15')
    description_prop = friendship.add_property('https://schema.org/description', 'Met at university')
    assert start_date_prop.value == '2018-03-15'
    assert description_prop.value == 'Met at university'

    # Add a new property to Ify
    job_prop = ify.add_property('https://schema.org/jobTitle', 'Software Engineer')
    assert job_prop.value == 'Software Engineer'

    # Modify a property by removing the old one and adding a new one
    old_age = None
    age_props = list(chuks.getprop('https://schema.org/age'))
    for prop in age_props:
        old_age = prop.value
        chuks.remove_property(prop)
    assert old_age == '28'
    chuks.add_property('https://schema.org/age', '29')

    # Verify the age was updated
    new_age = None
    for prop in chuks.getprop('https://schema.org/age'):
        new_age = prop.value
    assert new_age == '29'

    # Traverse edges
    found_friend = False
    for edge in chuks.traverse('https://schema.org/knows'):
        friend = edge.target
        assert friend == ify
        for name_prop in friend.getprop('https://schema.org/name'):
            assert name_prop.value == 'Ifeoma Adebayo'
            found_friend = True
        # Access nested properties on the edge
        for date_prop in edge.getprop('https://schema.org/startDate'):
            assert date_prop.value == '2018-03-15'
    assert found_friend

    # Find all nodes of a certain type
    people = list(g.typematch('https://schema.org/Person'))
    assert len(people) == 2

    # Verify both Chuks and Ify are in the results
    people_names = []
    for person in people:
        for name_prop in person.getprop('https://schema.org/name'):
            people_names.append(name_prop.value)
    assert 'Chukwuemeka Okafor' in people_names
    assert 'Ifeoma Adebayo' in people_names


def test_readme_example_edge_removal():
    '''Test edge removal functionality'''

    onya_text = '''
# @docheader

* @document: http://example.org/test
* @base: http://example.org/people/
* @schema: https://schema.org/

# Person1 [Person]

* name: Person One

# Person2 [Person]

* name: Person Two
'''

    g = graph()
    literate_lex.parse(onya_text, g)

    person1 = g['http://example.org/people/Person1']
    person2 = g['http://example.org/people/Person2']

    # Add an edge
    knows_edge = person1.add_edge('https://schema.org/knows', person2)
    assert len(list(person1.traverse('https://schema.org/knows'))) == 1

    # Remove the edge
    person1.remove_edge(knows_edge)
    assert len(list(person1.traverse('https://schema.org/knows'))) == 0
