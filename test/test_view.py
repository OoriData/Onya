# -*- coding: utf-8 -*-
# test/test_view.py
'''
Declarative read-side projection (`onya.view`): spec loading, ordering, cardinality, typed
values, follows (outbound / inbound / edge-on-edge), selection hooks, depth/cycle guards.

    pytest -s test/test_view.py
'''

import json
import tomllib
from decimal import Decimal

import pytest

from onya import view
from onya.serial import literate

L = 'http://example.org/lib/'

DOC = '''# @docheader
* @nodebase: http://example.org/lib/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab/

# ada [Person]
* name: Ada Lovelace
* email: countess@example.org
* email: ada@example.org
* worksFor -> analytical-engine-co
    * startDate: "1842"
    * ex:role -> ex:Translator
* knows -> babbage

# babbage [Person]
* name: Charles Babbage
* knows -> ada

# notes-on-the-engine [Book]
* name: Notes on the Analytical Engine
* datePublished: "1843"
* numberOfPages: 66
    * @as: number
* author -> ada

# sketch [Book]
* name: Sketch of the Analytical Engine
* datePublished: "1842"
* numberOfPages: not-a-number
    * @as: number
* author -> ada

# undated [Book]
* name: An Undated Letter
* author -> ada

# analytical-engine-co [Organization]
* name: Analytical Engine Company
* url: http://example.org/aec
'''

# ex:Translator is described in a second document, with its own vocabulary.
ROLES = '''# @docheader
* @schema: https://schema.org/

# http://example.org/vocab/Translator [DefinedTerm]
* name: Translator
'''

TOML = '''
[[view]]
type = "schema:Person"
fields = ["name", { label = "email", many = true }]

  [[view.follow]]
  edge = "worksFor"
  as = "employer"
  show = ["name", "url"]
  edge_props = ["startDate", "ex:role"]

  [[view.follow]]
  inbound = "author"
  as = "works"
  show = ["name", "datePublished"]
  limit = 10
  order_by = "datePublished"
'''


@pytest.fixture
def g():
    g = literate.read(DOC).graph
    literate.read(ROLES, g)
    return g


@pytest.fixture
def specs():
    return view.load(tomllib.loads(TOML))


def test_worked_example(g, specs):
    p = view.project(g, L + 'ada', specs)
    assert list(p) == ['id', 'type', 'label', 'fields', 'employer', 'works']
    assert p['id'] == L + 'ada' and p['type'] == 'Person' and p['label'] == 'Ada Lovelace'
    assert p['fields'] == [('name', 'Ada Lovelace'),
                           ('email', ['ada@example.org', 'countess@example.org'])]  # sorted
    [emp] = p['employer']
    assert emp == {'id': L + 'analytical-engine-co', 'label': 'Analytical Engine Company',
                   'fields': [('name', 'Analytical Engine Company'), ('url', 'http://example.org/aec')],
                   'edge': [('startDate', '1842'), ('ex:role', 'http://example.org/vocab/Translator')]}
    # order_by datePublished ascending; the undated book (missing value) sorts last
    assert [w['label'] for w in p['works']] == [
        'Sketch of the Analytical Engine', 'Notes on the Analytical Engine', 'An Undated Letter']
    assert json.dumps(view.jsonable(p))


def test_descending_order_and_limit(g):
    spec = {'type': 'Person', 'fields': ['name'],
            'follow': [{'inbound': 'author', 'show': ['name'], 'order_by': '-datePublished', 'limit': 2}]}
    p = view.project(g, L + 'ada', spec)
    assert [w['label'] for w in p['^author']] == ['Notes on the Analytical Engine',
                                                  'Sketch of the Analytical Engine']


def test_single_value_pick_is_deterministic(g):
    p = view.project(g, L + 'ada', {'type': 'Person', 'fields': ['email']})
    assert p['fields'] == [('email', 'ada@example.org')]  # the least, not an arbitrary one
    assert p['label'] == 'ada@example.org'


def test_typed_values_raw_and_malformed(g):
    spec = {'type': 'Book', 'fields': ['name', 'numberOfPages']}
    assert dict(view.project(g, L + 'notes-on-the-engine', spec)['fields'])['numberOfPages'] in (66, Decimal(66))
    assert dict(view.project(g, L + 'notes-on-the-engine', spec, raw=True)['fields'])['numberOfPages'] == '66'
    raw_field = {'type': 'Book', 'fields': [{'label': 'numberOfPages', 'raw': True, 'as': 'pages'}]}
    assert view.project(g, L + 'notes-on-the-engine', raw_field)['fields'] == [('pages', '66')]
    # malformed under @as: number -> shown raw, never an error
    assert dict(view.project(g, L + 'sketch', spec)['fields'])['numberOfPages'] == 'not-a-number'


def test_missing_data_is_fine(g):
    spec = {'type': 'Organization', 'fields': ['name', 'foundingDate'],
            'follow': [{'edge': 'subOrganization', 'show': ['name']}]}
    p = view.project(g, L + 'analytical-engine-co', spec)
    assert p['fields'] == [('name', 'Analytical Engine Company')]
    assert p['subOrganization'] == []


def test_edge_prop_follow(g):
    spec = {'type': 'Person', 'fields': ['name'], 'follow': [
        {'edge': 'worksFor', 'as': 'employer', 'show': ['name'],
         'edge_props': ['startDate', {'edge': 'ex:role', 'as': 'role', 'show': ['name']}]}]}
    [emp] = view.project(g, L + 'ada', spec)['employer']
    assert emp['edge'][0] == ('startDate', '1842')
    name, [role] = emp['edge'][1]
    assert name == 'role' and role['label'] == 'Translator' and role['id'] == 'http://example.org/vocab/Translator'


def test_showless_follow_uses_target_view_and_cycle_guard(g):
    specs = view.load([
        {'type': 'Person', 'fields': ['name'], 'follow': [{'edge': 'knows'}]},
    ])
    p = view.project(g, L + 'ada', specs)
    [bab] = p['knows']
    assert bab['type'] == 'Person' and bab['label'] == 'Charles Babbage'
    [back] = bab['knows']
    assert back == {'id': L + 'ada', 'type': 'Person', 'label': 'Ada Lovelace', 'truncated': 'cycle'}


def test_max_depth_truncates(g):
    specs = view.load([{'type': 'Person', 'fields': ['name'], 'follow': [{'edge': 'knows'}]}])
    p = view.project(g, L + 'ada', specs, max_depth=1)
    [bab] = p['knows']
    assert bab['truncated'] == 'depth' and 'knows' not in bab and bab['fields'] == [('name', 'Charles Babbage')]
    assert 'knows' not in view.project(g, L + 'ada', specs, max_depth=0)


def test_spec_selection_order_and_when(g):
    specs = view.load([
        {'when': 'prolific', 'fields': ['email']},
        {'type': ['Organization', 'Person'], 'fields': ['name']},
    ])

    def prolific(n, graph_):
        return len(list(graph_.inbound(n, label='author'))) >= 3
    assert view.project(g, L + 'ada', specs, predicates={'prolific': prolific})['fields'] == \
        [('email', 'ada@example.org')]
    assert view.project(g, L + 'babbage', specs, predicates={'prolific': prolific})['fields'] == \
        [('name', 'Charles Babbage')]
    with pytest.raises(KeyError, match='prolific'):
        view.project(g, L + 'ada', specs)
    callable_spec = view.load([{'when': lambda n, _: n.id.endswith('babbage'), 'fields': ['name']}])
    assert view.project(g, L + 'babbage', callable_spec)['label'] == 'Charles Babbage'
    assert view.project(g, L + 'ada', callable_spec) == {'id': L + 'ada', 'label': None, 'fields': []}


def test_forced_spec(g, specs):
    p = view.project(g, L + 'babbage', specs, spec={'fields': ['name']})
    assert p == {'id': L + 'babbage', 'label': 'Charles Babbage', 'fields': [('name', 'Charles Babbage')]}


def test_labels_candidates_and_templates(g):
    def label(spec_label):
        return view.project(g, L + 'ada', {'type': 'Person', 'label': spec_label, 'fields': ['email']})['label']
    assert label(['givenName', 'name']) == 'Ada Lovelace'            # first present candidate
    assert label('{name} <{email}>') == 'Ada Lovelace <ada@example.org>'
    assert label(['{givenName} {familyName}', 'name']) == 'Ada Lovelace'  # template needs all parts
    assert label('{schema:name}') == 'Ada Lovelace'                 # CURIE placeholders work
    assert label('nothing') is None


@pytest.mark.parametrize('bad,msg', [
    ({'type': 'Person', 'feilds': []}, 'Unknown view key'),
    ({'follow': [{'edge': 'a', 'inbound': 'b'}]}, 'exactly one'),
    ({'follow': [{'edge': 'a', 'as': 'fields'}]}, 'reserved'),
    ({'follow': [{'edge': 'a'}, {'edge': 'a'}]}, 'both be output'),
    ({'follow': [{'edge': 'a', 'follow': [{'edge': 'b'}]}]}, 'needs `show`'),
    ({'fields': [{'as': 'x'}]}, 'needs a `label`'),
    ({'follow': [{'edge': 'a', 'edge_props': [{'inbound': 'b'}]}]}, 'not inbound'),
])
def test_load_rejects_bad_specs(bad, msg):
    with pytest.raises(ValueError, match=msg):
        view.load(bad)


def test_name_errors_explain_the_fix():
    with pytest.raises(ValueError) as e:
        view.load({'type': 'Person', 'follow': [{'edge': 'worksFor', 'as': 'fields'}]})
    msg = str(e.value)
    assert msg.startswith("View `type = 'Person'`: follow `edge = \"worksFor\"` has `as = \"fields\"`")
    assert 'Pick another name, e.g. `as = "worksFor"`' in msg
    with pytest.raises(ValueError) as e:
        view.load({'type': 'Person', 'follow': [{'edge': 'label'}]})
    assert 'defaults to its label' in str(e.value) and 'Add an `as`' in str(e.value)
    assert '`as = "label_links"`' in str(e.value)
    with pytest.raises(ValueError) as e:
        view.load({'type': 'Person', 'follow': [{'edge': 'knows'}, {'edge': 'knows', 'show': ['name']}]})
    assert '`as = "knows_2"` on the second' in str(e.value)
    with pytest.raises(ValueError) as e:
        view.load({'type': 'Person', 'follow': [{'edge': 'worksFor', 'show': ['name'],
                                                  'follow': [{'inbound': 'id'}, {'edge': '^id'}]}]})
    assert str(e.value).startswith('Inside follow `edge = "worksFor"`: follows `inbound = "id"` and `edge = "^id"`')


def test_ids_and_edge_targets_are_iris(g):
    from amara.iri import I
    p = view.project(g, L + 'ada', {'type': 'Person', 'fields': ['name', 'worksFor'],
                                    'follow': [{'edge': 'knows', 'show': ['name']}]})
    assert isinstance(p['id'], I) and isinstance(p['knows'][0]['id'], I)
    fields = dict(p['fields'])
    assert isinstance(fields['worksFor'], I) and not isinstance(fields['name'], I)
    assert fields['worksFor'] == L + 'analytical-engine-co'   # still equal to the plain string
    assert json.loads(json.dumps(p))['id'] == L + 'ada'       # and JSON-encodable as-is
    assert type(view.jsonable(p)['id']) is str


def test_unknown_prefix_in_spec_raises(g):
    from onya.graph import UnknownPrefixError
    with pytest.raises(UnknownPrefixError):
        view.project(g, L + 'ada', {'type': 'Person', 'fields': ['foaf:name']})


def test_to_text(g, specs):
    text = view.to_text(view.project(g, L + 'ada', specs))
    assert text.splitlines()[0] == 'Ada Lovelace [Person]'
    assert '~startDate: 1842' in text and 'works:' in text


def test_view_does_not_import_store():
    import subprocess
    import sys
    code = ('import sys, onya.view; '
            "leaked = [m for m in sys.modules if m.startswith('onya.store')]; "
            "assert not leaked, leaked; print('OK')")
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert r.returncode == 0 and 'OK' in r.stdout, r.stderr
