# -*- coding: utf-8 -*-
# test/test_view.py
'''
Declarative read-side projection (`onya.view`): spec loading, ordering, cardinality, typed
values, follows (outbound / inbound / edge-on-edge), selection hooks, depth/cycle guards.

    pytest -s test/test_view.py
'''

import functools
import json
import tomllib
import warnings
from decimal import Decimal

import pytest

from onya import view
from onya.serial import literate

# The 0.6.0 output shape (no deprecated 'label' copy); the legacy default has its own tests below.
project = functools.partial(view.project, legacy_label=False)

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
    p = project(g, L + 'ada', specs)
    assert list(p) == ['id', 'type', 'title', 'fields', 'employer', 'works']
    assert p['id'] == L + 'ada' and p['type'] == 'Person' and p['title'] == 'Ada Lovelace'
    assert p['fields'] == [('name', 'Ada Lovelace'),
                           ('email', ['ada@example.org', 'countess@example.org'])]  # sorted
    [emp] = p['employer']
    assert emp == {'id': L + 'analytical-engine-co', 'title': 'Analytical Engine Company',
                   'fields': [('name', 'Analytical Engine Company'), ('url', 'http://example.org/aec')],
                   'edge': [('startDate', '1842'), ('ex:role', 'http://example.org/vocab/Translator')]}
    # order_by datePublished ascending; the undated book (missing value) sorts last
    assert [w['title'] for w in p['works']] == [
        'Sketch of the Analytical Engine', 'Notes on the Analytical Engine', 'An Undated Letter']
    assert json.dumps(view.jsonable(p))


def test_descending_order_and_limit(g):
    spec = {'type': 'Person', 'fields': ['name'],
            'follow': [{'inbound': 'author', 'show': ['name'], 'order_by': '-datePublished', 'limit': 2}]}
    p = project(g, L + 'ada', spec)
    assert [w['title'] for w in p['^author']] == ['Notes on the Analytical Engine',
                                                  'Sketch of the Analytical Engine']


def test_single_value_pick_is_deterministic(g):
    p = project(g, L + 'ada', {'type': 'Person', 'fields': ['email']})
    assert p['fields'] == [('email', 'ada@example.org')]  # the least, not an arbitrary one
    assert p['title'] == 'ada@example.org'


def test_typed_values_raw_and_malformed(g):
    spec = {'type': 'Book', 'fields': ['name', 'numberOfPages']}
    assert dict(project(g, L + 'notes-on-the-engine', spec)['fields'])['numberOfPages'] in (66, Decimal(66))
    assert dict(project(g, L + 'notes-on-the-engine', spec, raw=True)['fields'])['numberOfPages'] == '66'
    raw_field = {'type': 'Book', 'fields': [{'label': 'numberOfPages', 'raw': True, 'as': 'pages'}]}
    assert project(g, L + 'notes-on-the-engine', raw_field)['fields'] == [('pages', '66')]
    # malformed under @as: number -> shown raw, never an error
    assert dict(project(g, L + 'sketch', spec)['fields'])['numberOfPages'] == 'not-a-number'


def test_missing_data_is_fine(g):
    spec = {'type': 'Organization', 'fields': ['name', 'foundingDate'],
            'follow': [{'edge': 'subOrganization', 'show': ['name']}]}
    p = project(g, L + 'analytical-engine-co', spec)
    assert p['fields'] == [('name', 'Analytical Engine Company')]
    assert p['subOrganization'] == []


def test_edge_prop_follow(g):
    spec = {'type': 'Person', 'fields': ['name'], 'follow': [
        {'edge': 'worksFor', 'as': 'employer', 'show': ['name'],
         'edge_props': ['startDate', {'edge': 'ex:role', 'as': 'role', 'show': ['name']}]}]}
    [emp] = project(g, L + 'ada', spec)['employer']
    assert emp['edge'][0] == ('startDate', '1842')
    name, [role] = emp['edge'][1]
    assert name == 'role' and role['title'] == 'Translator' and role['id'] == 'http://example.org/vocab/Translator'


def test_showless_follow_uses_target_view_and_cycle_guard(g):
    specs = view.load([
        {'type': 'Person', 'fields': ['name'], 'follow': [{'edge': 'knows'}]},
    ])
    p = project(g, L + 'ada', specs)
    [bab] = p['knows']
    assert bab['type'] == 'Person' and bab['title'] == 'Charles Babbage'
    [back] = bab['knows']
    assert back == {'id': L + 'ada', 'type': 'Person', 'title': 'Ada Lovelace', 'truncated': 'cycle'}


def test_max_depth_truncates(g):
    specs = view.load([{'type': 'Person', 'fields': ['name'], 'follow': [{'edge': 'knows'}]}])
    p = project(g, L + 'ada', specs, max_depth=1)
    [bab] = p['knows']
    assert bab['truncated'] == 'depth' and 'knows' not in bab and bab['fields'] == [('name', 'Charles Babbage')]
    assert 'knows' not in project(g, L + 'ada', specs, max_depth=0)


def test_spec_selection_order_and_when(g):
    specs = view.load([
        {'when': 'prolific', 'fields': ['email']},
        {'type': ['Organization', 'Person'], 'fields': ['name']},
    ])

    def prolific(n, graph_):
        return len(list(graph_.inbound(n, label='author'))) >= 3
    assert project(g, L + 'ada', specs, predicates={'prolific': prolific})['fields'] == \
        [('email', 'ada@example.org')]
    assert project(g, L + 'babbage', specs, predicates={'prolific': prolific})['fields'] == \
        [('name', 'Charles Babbage')]
    with pytest.raises(KeyError, match='prolific'):
        project(g, L + 'ada', specs)
    callable_spec = view.load([{'when': lambda n, _: n.id.endswith('babbage'), 'fields': ['name']}])
    assert project(g, L + 'babbage', callable_spec)['title'] == 'Charles Babbage'
    assert project(g, L + 'ada', callable_spec) == {'id': L + 'ada', 'title': None, 'fields': []}


def test_forced_spec(g, specs):
    p = project(g, L + 'babbage', specs, spec={'fields': ['name']})
    assert p == {'id': L + 'babbage', 'title': 'Charles Babbage', 'fields': [('name', 'Charles Babbage')]}


def test_labels_candidates_and_templates(g):
    def label(spec_label):
        return project(g, L + 'ada', {'type': 'Person', 'title': spec_label, 'fields': ['email']})['title']
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
    p = project(g, L + 'ada', {'type': 'Person', 'fields': ['name', 'worksFor'],
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
        project(g, L + 'ada', {'type': 'Person', 'fields': ['foaf:name']})


def test_to_text(g, specs):
    text = view.to_text(project(g, L + 'ada', specs))
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


# --- prefer / order_by (0.5.1) -------------------------------------------------------------

PREFS = '''# @docheader
* @nodebase: http://example.org/lib/
* @schema: https://schema.org/
* @iri:
    * ex: http://example.org/vocab/

# ada [Person]
* name: Ada Lovelace
* email: ada@example.org
* email: countess@example.org
    * ex:use -> ex:Primary
* telephone: "+44 20 7946 0000"
    * ex:use -> ex:Work
    * ex:priority: 10
        * @as: number
* telephone: "+44 20 7946 0001"
    * ex:use -> ex:Home
    * ex:priority: 9
        * @as: number
* telephone: "+44 20 7946 0002"
* jobTitle: Translator
    * ex:primary: yes
* jobTitle: Analyst
    * ex:primary: true
        * @as: boolean
* worksFor -> aec
* worksFor -> royal-society
    * ex:current: true
        * @as: boolean

# aec [Organization]
* name: Analytical Engine Company

# royal-society [Organization]
* name: Royal Society
'''


@pytest.fixture
def pg():
    return literate.read(PREFS).graph


def fields_of(g, fields, **kw):
    return dict(project(g, L + 'ada', {'type': 'Person', 'fields': fields}, **kw)['fields'])


def test_prefer_edge_target_pattern(pg):
    f = fields_of(pg, [{'label': 'email', 'prefer': {'label': 'ex:use', 'target': 'ex:Primary'}}])
    assert f['email'] == 'countess@example.org'   # today's rule alone would pick ada@…
    assert fields_of(pg, ['email'])['email'] == 'ada@example.org'


def test_prefer_list_falls_through_in_order(pg):
    prefer = [{'label': 'ex:use', 'target': 'ex:Mobile'}, {'label': 'ex:use', 'target': 'ex:Home'}]
    assert fields_of(pg, [{'label': 'telephone', 'prefer': prefer}])['telephone'] == '+44 20 7946 0001'
    # nothing matches -> least value, exactly as before
    none = [{'label': 'ex:use', 'target': 'ex:Mobile'}]
    assert fields_of(pg, [{'label': 'telephone', 'prefer': none}])['telephone'] == '+44 20 7946 0000'


def test_prefer_value_typed_vs_string(pg):
    # typed spec value: matches only `@as`-interpreted True, never the string "yes"
    def pick(value):
        return fields_of(pg, [{'label': 'jobTitle', 'prefer': {'label': 'ex:primary', 'value': value}}])['jobTitle']
    assert pick(True) == 'Analyst'
    assert pick('yes') == 'Translator'   # a string spec value compares the stored text
    assert pick('true') == 'Analyst'


def test_prefer_presence_shorthand(pg):
    # `"ex:primary"`: any nested assertion with that label — both jobTitles carry one, so least wins
    assert fields_of(pg, [{'label': 'jobTitle', 'prefer': 'ex:primary'}])['jobTitle'] == 'Analyst'
    assert fields_of(pg, [{'label': 'email', 'prefer': 'ex:use'}])['email'] == 'countess@example.org'


def test_order_by_on_fields(pg):
    f = fields_of(pg, [{'label': 'telephone', 'order_by': 'ex:priority'}])
    assert f['telephone'] == '+44 20 7946 0001'          # 9 < 10 numerically (not as text)
    many = fields_of(pg, [{'label': 'telephone', 'order_by': 'ex:priority', 'many': True}])['telephone']
    assert many == ['+44 20 7946 0001', '+44 20 7946 0000', '+44 20 7946 0002']   # missing last
    desc = fields_of(pg, [{'label': 'telephone', 'order_by': '-ex:priority', 'many': True}])['telephone']
    assert desc == ['+44 20 7946 0000', '+44 20 7946 0001', '+44 20 7946 0002']   # missing still last


def test_prefer_then_order_by_and_many_ordering(pg):
    spec = {'label': 'telephone', 'many': True, 'order_by': 'ex:priority',
            'prefer': {'label': 'ex:use', 'target': 'ex:Work'}}
    assert fields_of(pg, [spec])['telephone'] == ['+44 20 7946 0000', '+44 20 7946 0001', '+44 20 7946 0002']
    emails = fields_of(pg, [{'label': 'email', 'many': True, 'prefer': 'ex:use'}])['email']
    assert emails == ['countess@example.org', 'ada@example.org']   # preferred first, nothing dropped


def test_title_placeholders_use_the_fields_pick(pg):
    spec = {'type': 'Person', 'title': '{name} <{email}>',
            'fields': [{'label': 'email', 'prefer': {'label': 'ex:use', 'target': 'ex:Primary'}}]}
    assert project(pg, L + 'ada', spec)['title'] == 'Ada Lovelace <countess@example.org>'


def test_prefer_on_follows(pg):
    spec = {'type': 'Person', 'fields': ['name'], 'follow': [
        {'edge': 'worksFor', 'as': 'employer', 'show': ['name'],
         'prefer': {'label': 'ex:current', 'value': True}, 'limit': 1}]}
    [emp] = project(pg, L + 'ada', spec)['employer']
    assert emp['title'] == 'Royal Society'            # alphabetical order alone would pick the AEC


def test_prefer_edge_props_field(pg):
    roles = ('* worksFor -> aec\n'
             '    * ex:role -> ex:Clerk\n'
             '    * ex:role -> ex:Translator\n'
             '        * ex:primary: true\n'
             '            * @as: boolean\n')
    g = literate.read(PREFS.replace('* worksFor -> aec\n', roles)).graph
    spec = {'type': 'Person', 'fields': ['name'], 'follow': [
        {'edge': 'worksFor', 'as': 'employer', 'show': ['name'],
         'edge_props': [{'label': 'ex:role', 'prefer': {'label': 'ex:primary', 'value': True}}]}]}
    emp = next(e for e in project(g, L + 'ada', spec)['employer'] if e['title'] == 'Analytical Engine Company')
    # patterns on an edge-valued field read *that edge's* nested assertions
    assert emp['edge'] == [('ex:role', 'http://example.org/vocab/Translator')]


def test_prefer_bare_target_is_rejected(pg):
    with pytest.raises(ValueError, match='full IRI or CURIE'):
        fields_of(pg, [{'label': 'email', 'prefer': {'label': 'ex:use', 'target': 'Primary'}}])


@pytest.mark.parametrize('bad,msg', [
    ({'fields': [{'label': 'email', 'prefer': {'label': 'ex:use', 'value': 'x', 'target': 'ex:Y'}}]}, 'not both'),
    ({'fields': [{'label': 'email', 'prefer': {'value': True}}]}, 'needs a `label`'),
    ({'fields': [{'label': 'email', 'prefer': {'label': 'ex:use', 'targte': 'ex:Y'}}]}, 'Unknown'),
    ({'fields': [{'label': 'email', 'prefer': 3}]}, 'label string or a table'),
    ({'fields': [{'label': 'email', 'order_by': 3}]}, '`order_by` is a label'),
    ({'follow': [{'edge': 'a', 'prefer': [{'label': 'x', 'target': 5}]}]}, 'IRI or CURIE string'),
])
def test_prefer_order_by_load_errors(bad, msg):
    with pytest.raises(ValueError, match=msg):
        view.load(bad)


# --- deprecation shims (remove in 0.6.0) ---------------------------------------------------

def test_label_spec_key_deprecated_but_works(g):
    with pytest.warns(DeprecationWarning, match='use `title =`'):
        specs = view.load({'type': 'Person', 'label': '{name}!', 'fields': ['email']})
    assert project(g, L + 'ada', specs)['title'] == 'Ada Lovelace!'
    with pytest.warns(DeprecationWarning, match='use `title =`'):
        specs = view.load({'type': 'Person', 'fields': ['name'],
                           'follow': [{'edge': 'worksFor', 'label': 'url', 'show': ['name', 'url']}]})
    assert project(g, L + 'ada', specs)['worksFor'][0]['title'] == 'http://example.org/aec'
    with pytest.raises(ValueError, match='give `title` only'):
        view.load({'type': 'Person', 'label': 'x', 'title': 'y'})
    with pytest.warns(DeprecationWarning, match='View.title'):
        assert specs[0].label_spec is None


def test_legacy_label_output_key(g, specs):
    p = view.project(g, L + 'ada', specs)                       # default: legacy copy present
    assert list(p)[:4] == ['id', 'type', 'title', 'label']
    assert json.loads(json.dumps(p))['label'] == 'Ada Lovelace'  # JSON consumers unaffected
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        p['title'], dict(p), view.jsonable(p), view.to_text(p)  # no warning without touching 'label'
    with pytest.warns(DeprecationWarning, match="use 'title'"):
        assert p['label'] == 'Ada Lovelace'
    with pytest.warns(DeprecationWarning):
        assert p['employer'][0].get('label') == 'Analytical Engine Company'
    assert 'label' not in view.project(g, L + 'ada', specs, legacy_label=False)
