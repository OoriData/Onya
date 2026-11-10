# -*- coding: utf-8 -*-
# test/test_shape.py
'''
The shape layer (`onya.shape`): declarations are ordinary nodes, validation reports and never mutates.

    pytest -s test/test_shape.py
'''

import copy

import pytest

from onya.digest import digest
from onya.graph import GraphMergeError, graph
from onya.serial.literate import read, write
from onya.shape import Shapes, load_shapes, parse_cardinality, validate
from onya.terms import RESERVED

# nodebase == schema, so a declaration's node id is the label/class IRI it is about
HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
'''

SHAPES = '''
# Person [@Class]
* @label: Person

# Student [@Class]
* @subClassOf -> Person

# Org [@Class]

# name [@Property]
* @appliesTo -> Person
* @as: text
* @cardinality: 1

# jobTitle [@Property]
* @appliesTo -> Person
* @cardinality: 0..*

# knows [@Property]
* @appliesTo -> Person
* @range -> Person

# status [@Property]
* @appliesTo -> Student
* @oneOf: active
* @oneOf: closed
* @cardinality: 1

# age [@Property]
* @as: integer
'''

DATA = '''
# chuks [Person]
* name: Chuks
* knows -> ify
* age: 28

# ify [Student]
* name: Ify
* status: active
'''


def _g(*parts):
    g = graph()
    read(HEAD + ''.join(parts), g, track_locations=True)
    return g


def _kinds(report):
    return sorted((f.kind, str(f.node).rsplit('/', 1)[-1], str(f.label).rsplit('/', 1)[-1]) for f in report.findings)


def test_a_conforming_graph_has_no_findings():
    g = _g(SHAPES, DATA)
    r = validate(g)
    assert r.ok and str(r) == 'Report: ok (no findings)', str(r)


def test_shapes_can_live_in_a_separate_graph():
    data, shapes = _g(DATA), _g(SHAPES)
    assert validate(data, shapes).ok
    assert validate(data, load_shapes(shapes)).ok  # or precompiled
    assert not validate(_g(DATA.replace('active', 'dormant')), shapes).ok


def test_one_of():
    r = validate(_g(SHAPES, DATA.replace('status: active', 'status: dormant')))
    assert _kinds(r) == [('one_of', 'ify', 'status')]
    assert "'dormant'" in r.findings[0].detail and 'active' in r.findings[0].detail


@pytest.mark.parametrize('spec, expect', [
    ('1', (1, 1)), ('0..1', (0, 1)), ('1..*', (1, None)), ('0..*', (0, None)), ('*', (0, None)),
    ('2..5', (2, 5)), (' 3 ', (3, 3)),
])
def test_cardinality_forms(spec, expect):
    assert parse_cardinality(spec) == expect


@pytest.mark.parametrize('bad', ['', 'many', '1..', '..1', '3..1', '-1', '1...2', 'one'])
def test_bad_cardinalities(bad):
    with pytest.raises(ValueError, match='not a cardinality'):
        parse_cardinality(bad)


def test_cardinality_max_and_min():
    two = validate(_g(SHAPES, DATA.replace('* name: Chuks', '* name: Chuks\n* name: Chuk')))
    assert _kinds(two) == [('cardinality', 'chuks', 'name')] and 'has 2, declared 1' in two.findings[0].detail
    none = validate(_g(SHAPES, DATA.replace('* name: Chuks\n', '')))
    assert _kinds(none) == [('cardinality', 'chuks', 'name')] and 'has 0, declared 1' in none.findings[0].detail


def test_identical_values_are_one_claim_for_cardinality():
    r = validate(_g(SHAPES, DATA.replace('* name: Chuks', '* name: Chuks\n* name: Chuks')))
    assert r.ok  # unmerged duplicates are one claim, as they would be after a merge


def test_applies_to_is_any_of_and_closes_over_subclasses():
    ok = validate(_g(SHAPES, '\n# s [Student]\n* name: S\n* status: closed\n'))  # `name` applies to Person, a parent
    assert ok.ok
    r = validate(_g(SHAPES, '\n# acme [Org]\n* name: Acme\n'))
    assert _kinds(r) == [('applies_to', 'acme', 'name')]
    assert validate(_g(SHAPES, '\n# x\n* jobTitle: CEO\n')).findings[0].kind == 'applies_to'  # untyped fails it too


def test_applies_to_any_of_several_classes():
    r = validate(_g(SHAPES.replace('# jobTitle [@Property]\n* @appliesTo -> Person',
                                   '# jobTitle [@Property]\n* @appliesTo -> Person\n* @appliesTo -> Org'),
                    '\n# acme [Org]\n* jobTitle: n/a\n'))
    assert r.ok


def test_range_follows_subclasses_and_reports_wrong_and_untyped_targets():
    assert validate(_g(SHAPES, DATA)).ok  # chuks knows ify, a Student, so a Person
    r = validate(_g(SHAPES, DATA.replace('knows -> ify', 'knows -> acme') + '\n# acme [Org]\n* label: x\n'))
    assert _kinds(r) == [('range', 'chuks', 'knows')] and 'acme' in r.findings[0].detail
    untyped = validate(_g(SHAPES, DATA.replace('knows -> ify', 'knows -> ghost')))
    assert _kinds(untyped) == [('range', 'chuks', 'knows')] and 'untyped' in untyped.findings[0].detail


def test_value_where_an_edge_is_declared_and_the_reverse():
    r = validate(_g(SHAPES, DATA.replace('knows -> ify', 'knows: ify')))
    assert 'declared as an edge' in r.findings[0].detail and r.findings[0].kind == 'range'
    r = validate(_g(SHAPES, DATA.replace('age: 28', 'age -> ify')))
    assert r.findings[0].kind == 'range' and 'declared as a value' in r.findings[0].detail


def test_as_on_a_declaration_is_the_default_for_that_label():
    r = validate(_g(SHAPES, DATA.replace('age: 28', 'age: twenty')))
    assert _kinds(r) == [('as', 'chuks', 'age')] and "'twenty' is not a valid" in r.findings[0].detail
    assert validate(_g(SHAPES, DATA.replace('age: 28', 'age: 007'))).ok  # `007` is an integer
    # the data's own @as is checked too, at any depth, with or without a declaration
    nested = validate(_g(DATA + '* knows -> ify\n  * since: soon\n    * @as: integer\n'))
    assert _kinds(nested) == [('as', 'ify', 'since')]  # DATA's last block is ify


def test_an_own_as_beats_the_declared_default():
    own = DATA.replace('age: 28', 'age: 2.5\n  * @as: number')
    assert validate(_g(SHAPES, own)).ok  # number accepts it; the shape's integer is only a default


def test_open_by_default_and_closed_on_request():
    extra = DATA.replace('* age: 28', '* age: 28\n* shoeSize: 9')
    assert validate(_g(SHAPES, extra)).ok
    closed = SHAPES.replace('# Person [@Class]\n', '# Person [@Class]\n* @closed: true\n')
    r = validate(_g(closed, extra))
    assert _kinds(r) == [('undeclared_label', 'chuks', 'shoeSize')]
    # ... and a label declared for a parent class is fine on a subclass, and `age` has no appliesTo (any node)
    assert validate(_g(closed, DATA)).ok
    # `@` terms are never "undeclared"
    assert validate(_g(closed, DATA.replace('* age: 28', '* age: 28\n  * @source: x'))).ok


def test_severity_comes_from_the_declaration():
    soft = SHAPES.replace('# status [@Property]\n', '# status [@Property]\n* @severity: warning\n')
    r = validate(_g(soft, DATA.replace('active', 'dormant')))
    assert [(f.severity, f.kind) for f in r.findings] == [('warning', 'one_of')]
    assert r.errors == [] and len(r.warnings) == 1 and not r.ok


def test_ordered_declaration_checks_the_stamps():
    decl = SHAPES + '\n# hobby [@Property]\n* @ordered: true\n'
    good = DATA + '* hobby: chess\n  * @ordering: 1\n* hobby: go\n  * @ordering: 2\n'
    assert validate(_g(decl, good)).ok
    r = validate(_g(decl, DATA + '* hobby: chess\n* hobby: go\n  * @ordering: 2\n'))
    assert _kinds(r) == [('ordering', 'ify', 'hobby')] and 'no @ordering' in r.findings[0].detail
    r = validate(_g(decl, DATA + '* hobby: chess\n  * @ordering: x\n'))
    assert 'not an integer' in r.findings[0].detail


def test_findings_carry_locations_when_tracked():
    r = validate(_g(SHAPES, DATA.replace('active', 'dormant')))
    (f,) = r.findings
    assert f.location.line.strip() == '* status: dormant'
    assert '(at http://e.o/doc:' in str(f)
    plain = graph()
    read(HEAD + SHAPES + DATA.replace('active', 'dormant'), plain)
    assert '(location not tracked)' in str(validate(plain).findings[0])


def test_unknown_reserved_terms_are_warnings():
    r = validate(_g(SHAPES, DATA + '* @Calss: x\n'))
    assert [(f.severity, f.kind) for f in r.findings] == [('warning', 'unknown_reserved_term')]


def test_dangling_is_opt_in_and_allows():
    g = _g(SHAPES, DATA.replace('knows -> ify', 'knows -> ify\n* knows -> https://orcid.org/0000\n* knows -> typo'))
    quiet = validate(g)
    assert 'dangling' not in {f.kind for f in quiet.findings}
    r = validate(g, dangling=True, allow='https://orcid.org/')
    assert [f.kind for f in r.findings if f.kind == 'dangling'] == ['dangling'] and 'typo' in str(r.findings[-1])


def test_malformed_declarations_are_findings_not_exceptions():
    bad = '''
# p [@Property]
* @cardinality: lots
* @severity: loud
* @as: integer
* @range -> Person

# Person [@Class]
* @closed: maybe
'''
    r = validate(_g(bad))
    kinds = [(f.kind, str(f.label).rsplit('/', 1)[-1]) for f in r.findings]
    assert sorted(kinds) == [('bad_shape', 'cardinality'), ('bad_shape', 'closed'), ('bad_shape', 'range'),
                             ('bad_shape', 'severity')]


def test_validation_never_mutates():
    g = _g(SHAPES, DATA.replace('active', 'dormant') + '* shoeSize: 9\n')
    before = (sorted((str(n.id), sorted(map(str, n.types)), len(n.properties), len(n.edges)) for n in g.nodes.values()),
              {str(k): copy.copy(v) for k, v in g.prefixes.items()})
    validate(g, dangling=True)
    after = (sorted((str(n.id), sorted(map(str, n.types)), len(n.properties), len(n.edges)) for n in g.nodes.values()),
             {str(k): v for k, v in g.prefixes.items()})
    assert before == after  # no inferred types, nodes or values


def test_declarations_are_not_checked_as_data():
    '''A Property node has `@appliesTo` and friends on it: it must not be judged against Person, say.'''
    assert validate(_g(SHAPES, DATA.replace('# chuks [Person]', '# chuks [Person]'))).ok


def test_node_level_as_is_kept_and_round_trips():
    g = _g(SHAPES)
    shape = load_shapes(g)
    assert str(shape.properties['http://e.o/age'].interp).endswith('/interp/integer')
    import io
    buf = io.StringIO()
    write(g, buf, document='http://e.o/doc', nodebase='http://e.o/', schema='http://e.o/')
    assert '* @as: integer' in buf.getvalue()  # a reserved name stays a bare name
    g2 = graph()
    read(buf.getvalue(), g2)
    assert load_shapes(g2).properties['http://e.o/age'].interp == shape.properties['http://e.o/age'].interp


def test_shapes_object_exposes_the_tables():
    sh = load_shapes(_g(SHAPES))
    assert isinstance(sh, Shapes)
    assert set(sh.classes) == {'http://e.o/Person', 'http://e.o/Student', 'http://e.o/Org'}
    assert sh.classes['http://e.o/Person'].label == 'Person'
    assert sh.properties['http://e.o/status'].one_of == {'active', 'closed'}
    assert sh.properties['http://e.o/knows'].range == {'http://e.o/Person'}
    assert sh.closure(['http://e.o/Student']) == {'http://e.o/Student', 'http://e.o/Person'}


def test_a_subclass_cycle_terminates():
    cyc = '\n# A [@Class]\n* @subClassOf -> B\n\n# B [@Class]\n* @subClassOf -> A\n'
    assert load_shapes(_g(cyc)).closure(['http://e.o/A']) == {'http://e.o/A', 'http://e.o/B'}


def test_shape_terms_are_reserved_by_the_shape_layer():
    for t in ('Class', 'Property', 'label', 'subClassOf', 'appliesTo', 'range', 'cardinality', 'oneOf', 'closed',
              'severity'):
        assert RESERVED[t] == 'shape'


def test_cli_validate(tmp_path, capsys):
    from onya.cli.onya import validate as cli_validate
    (tmp_path / 'shapes.onya').write_text(HEAD + SHAPES)
    (tmp_path / 'data.onya').write_text(HEAD.replace('e.o/doc', 'e.o/doc2') + DATA.replace('active', 'dormant'))
    with pytest.raises(SystemExit) as e:
        cli_validate(str(tmp_path))  # shapes and data in one directory: one graph
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert 'error one_of' in out and 'data.onya:13)' in out  # names the file and line
    (tmp_path / 'data.onya').write_text(HEAD.replace('e.o/doc', 'e.o/doc2') + DATA)
    cli_validate(str(tmp_path))  # clean: returns without exiting
    assert 'error' not in capsys.readouterr().out


def test_cli_validate_strict_and_separate_shapes(tmp_path, capsys):
    from onya.cli.onya import validate as cli_validate
    shapes = tmp_path / 'shapes'
    data = tmp_path / 'data'
    shapes.mkdir()
    data.mkdir()
    (shapes / 's.onya').write_text(HEAD + SHAPES)
    (data / 'd.onya').write_text(HEAD + DATA + '* @Calss: x\n')
    cli_validate(str(data), shapes=str(shapes))  # a warning only: passes
    assert 'warning unknown_reserved_term' in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli_validate(str(data), shapes=str(shapes), strict=True)
    assert e.value.code == 2


# --- validate(fragment, against=base): a proposed change, checked as if merged into the base -----------------------

BASE = SHAPES + '''
# acme [Org]

# chuks [Student]
* name: Chuks
* status: active

# adat [Person]
* name: Adat

# nameless [Person]
'''  # `nameless` breaks `name`'s cardinality 1: the base's own problem


def _base():
    return _g(BASE)


def test_a_fragment_alone_cannot_see_the_types_of_the_base_but_against_resolves_them():
    frag = _g('# ify [Person]\n* name: Ify\n* knows -> chuks\n')
    alone = validate(frag, shapes=_base())
    assert ('range', 'http://e.o/ify') in {(f.kind, str(f.node)) for f in alone.findings}  # chuks looks untyped
    assert validate(frag, against=_base()).findings == []  # chuks is a Student, a Person, in the base


def test_against_still_reports_a_target_of_the_wrong_type_in_the_base():
    frag = _g('# ify [Person]\n* name: Ify\n* knows -> acme\n')
    [f] = validate(frag, against=_base()).findings
    assert (f.kind, str(f.node)) == ('range', 'http://e.o/ify') and 'acme' in f.detail


def test_against_counts_what_the_base_already_holds_for_a_node_the_fragment_adds_to():
    frag = _g('# chuks [Student]\n* name: Chukwuemeka\n')  # a second name for a cardinality-1 property
    [f] = validate(frag, against=_base()).findings
    assert (f.kind, str(f.node), f.detail) == ('cardinality', 'http://e.o/chuks', 'has 2, declared 1')
    alone = validate(frag, shapes=_base())  # alone, the fragment misses the Student's `status` the base holds
    assert 'http://e.o/status' in {str(f.label) for f in alone.findings}
    assert 'http://e.o/status' not in {str(f.label) for f in validate(frag, against=_base()).findings}


def test_the_bases_own_problems_are_not_reported():
    assert [str(f.node) for f in validate(_base()).findings] == ['http://e.o/nameless']  # it is there to be seen
    frag = _g('# ify [Person]\n* name: Ify\n')
    assert validate(frag, against=_base()).findings == []  # but the fragment never touched it
    touched = _g('# nameless [Person]\n* jobTitle: nobody\n')
    assert [str(f.node) for f in validate(touched, against=_base()).findings] == ['http://e.o/nameless']


def test_against_takes_its_shapes_from_the_base_and_applies_them_to_new_nodes():
    frag = _g('# widget [Org]\n* name: Widget\n')  # `name` is for Person; the fragment declares nothing
    assert {f.kind for f in validate(frag, against=_base()).findings} == {'applies_to'}


def test_against_changes_neither_graph():
    base, frag = _base(), _g('# chuks [Student]\n* name: Chukwuemeka\n* knows -> adat\n')
    before = (digest(base), digest(frag))
    validate(frag, against=base)
    assert (digest(base), digest(frag)) == before


def test_against_with_dangling_resolves_targets_through_the_base():
    frag = _g('# ify [Person]\n* name: Ify\n* knows -> adat\n* knows -> nobody\n')
    found = validate(frag, against=_base(), dangling=True).findings
    assert [(f.kind, f.detail.split()[1]) for f in found if f.kind == 'dangling'] == [('dangling', 'http://e.o/nobody')]


def test_the_work_is_bounded_by_the_fragment_not_the_base(monkeypatch):
    big = _g(BASE + ''.join(f'\n# p{i} [Person]\n* name: P{i}\n' for i in range(500)))
    sizes = []
    real = type(big).subgraph

    def spy(self, roots, hops=1):
        out = real(self, roots, hops)
        sizes.append(len(out.nodes))
        return out

    monkeypatch.setattr(type(big), 'subgraph', spy)
    assert validate(_g('# ify [Person]\n* name: Ify\n* knows -> adat\n'), against=big).findings == []
    assert sizes and max(sizes) < 10  # not the 500


def test_a_fragment_that_cannot_merge_into_the_base_raises_as_a_put_would():
    base = _g(BASE, '\n# a [Person]\n* name: A\n* age: 28 [=p1]\n')
    frag = _g('# a [Person]\n* age: 29 [=p1]\n')  # the same assertion id, different content
    with pytest.raises(GraphMergeError):
        validate(frag, against=base)


def test_a_broken_neighbor_of_a_touched_node_is_copied_in_but_not_reported():
    '''The one-hop copy brings `nameless` along (it is adat's friend); the report must still leave it out.'''
    base = _g(BASE.replace('* name: Adat\n', '* name: Adat\n* knows -> nameless\n'))
    frag = _g('# ify [Person]\n* name: Ify\n* knows -> adat\n')
    assert [str(f.node) for f in validate(base).findings] == ['http://e.o/nameless']
    assert validate(frag, against=base).findings == []


def test_cli_validate_a_fragment_against_a_base(tmp_path, capsys):
    from onya.cli.onya import validate as cli_validate
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'kg.onya').write_text(HEAD + BASE)
    ok, bad = tmp_path / 'ok.onya', tmp_path / 'bad.onya'
    ok.write_text(HEAD + '\n# ify [Person]\n* name: Ify\n* knows -> chuks\n')
    bad.write_text(HEAD + '\n# ify [Person]\n* name: Ify\n* knows -> acme\n')
    cli_validate(str(ok), against=str(base))  # chuks resolves through the base; its `nameless` is not reported
    with pytest.raises(SystemExit) as e:
        cli_validate(str(bad), against=str(base))
    assert e.value.code == 2
    assert 'acme' in capsys.readouterr().out


def test_cli_validate_a_fragment_against_a_store(tmp_path, capsys):
    import asyncio

    from onya.cli.onya import validate as cli_validate
    from onya.store import connect

    async def seed():
        async with await connect(f'sqlite:{tmp_path}/kg.db') as st:
            await st.put('http://e.o/doc', _g(BASE))
    asyncio.run(seed())
    ok, bad = tmp_path / 'ok.onya', tmp_path / 'bad.onya'
    ok.write_text(HEAD + '\n# ify [Person]\n* name: Ify\n* knows -> chuks\n')
    bad.write_text(HEAD + '\n# ify [Person]\n* name: Ify\n* knows -> acme\n')
    cli_validate(str(ok), store=f'sqlite:{tmp_path}/kg.db', graph='http://e.o/doc')
    with pytest.raises(SystemExit):
        cli_validate(str(bad), store=f'sqlite:{tmp_path}/kg.db', graph='http://e.o/doc')
    with pytest.raises(SystemExit, match='--graph'):
        cli_validate(str(ok), store=f'sqlite:{tmp_path}/kg.db')
