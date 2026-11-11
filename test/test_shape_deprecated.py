# -*- coding: utf-8 -*-
# test/test_shape_deprecated.py
'''
`@deprecated` and `@replacedBy` on a `@Property` or `@Class`: a `deprecated` warning wherever one is used.

    pytest -s test/test_shape_deprecated.py
'''

import pytest

from onya.graph import graph
from onya.serial.literate import read
from onya.shape import load_shapes, validate
from onya.terms import unknown_reserved_terms

HEAD = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/
'''

SHAPES = '''
# Person [@Class]
# Human [@Class]
* @deprecated: Use Person.
* @replacedBy -> Person
# Legacy [@Class]
* @replacedBy -> Person
# Child [@Class]
* @subClassOf -> Human

# nickname [@Property]
* @appliesTo -> Person
* @deprecated: Use preferredName instead; nickname loses the language.
* @replacedBy -> preferredName
# preferredName [@Property]
* @appliesTo -> Person
# aka [@Property]
* @appliesTo -> Person
* @deprecated: Going away.
# oldAka [@Property]
* @appliesTo -> Person
* @replacedBy -> aka
'''


def _g(data='', shapes=SHAPES):
    g = graph()
    read(HEAD + shapes + data, g, track_locations=True)
    return g


def _found(g, **kw):
    return [f for f in validate(g, **kw).findings if f.kind == 'deprecated']


def test_a_deprecated_label_warns_with_its_guidance_and_replacement():
    (f,) = _found(_g('\n# ada [Person]\n* nickname: Ada\n'))
    assert f.severity == 'warning' and str(f.node) == 'http://e.o/ada' and str(f.label) == 'http://e.o/nickname'
    assert 'Use preferredName instead; nickname loses the language.' in f.detail
    assert 'Replaced by http://e.o/preferredName.' in f.detail
    assert 'http://e.o/doc:' in str(f)  # names the line


def test_a_node_using_the_label_twice_gets_one_finding():
    assert len(_found(_g('\n# ada [Person]\n* nickname: Ada\n* nickname: Ad\n'))) == 1


def test_a_deprecated_class_warns_on_each_node_typed_with_it():
    fs = _found(_g('\n# ada [Human]\n# bo [Human]\n# cy [Person]\n'))
    assert sorted(str(f.node) for f in fs) == ['http://e.o/ada', 'http://e.o/bo']
    assert 'class http://e.o/Human is deprecated: Use Person. Replaced by http://e.o/Person.' == fs[0].detail


def test_a_subclass_of_a_deprecated_class_is_not_itself_deprecated():
    assert _found(_g('\n# ada [Child]\n')) == []


def test_replaced_by_alone_marks_it_deprecated():
    (f,) = _found(_g('\n# ada [Legacy]\n'))
    assert f.detail == 'class http://e.o/Legacy is deprecated. Replaced by http://e.o/Person.'
    (f,) = _found(_g('\n# ada [Person]\n* oldAka: x\n'))
    assert f.detail == 'label http://e.o/oldAka is deprecated. Replaced by http://e.o/aka.'


def test_guidance_alone_has_no_replacement_text():
    (f,) = _found(_g('\n# ada [Person]\n* aka: x\n'))
    assert f.detail == 'label http://e.o/aka is deprecated: Going away.'


def test_nothing_uses_them_and_the_declarations_are_not_flagged():
    r = validate(_g('\n# ada [Person]\n* preferredName: Ada\n'))
    assert r.ok  # the deprecated declarations themselves are not data
    assert unknown_reserved_terms(_g()) == {}  # and not typos


def test_severity_on_the_declaration_does_not_change_it():
    s = SHAPES.replace('* @deprecated: Going away.', '* @deprecated: Going away.\n* @severity: error')
    (f,) = _found(_g('\n# ada [Person]\n* aka: x\n', s))
    assert f.severity == 'warning'


def test_two_deprecated_notes_are_a_bad_declaration():
    s = SHAPES.replace('* @deprecated: Going away.', '* @deprecated: Going away.\n* @deprecated: Or not.')
    assert any(f.kind == 'bad_shape' and 'at most one @deprecated' in f.detail for f in validate(_g('', s)).findings)


def test_shapes_expose_it():
    sh = load_shapes(_g())
    assert sh.properties['http://e.o/nickname'].deprecated.startswith('Use preferredName')
    assert sh.properties['http://e.o/nickname'].replaced_by == ('http://e.o/preferredName',)
    assert sh.properties['http://e.o/preferredName'].deprecated is None
    assert sh.classes['http://e.o/Legacy'].deprecated == ''


def test_a_fragment_checked_against_a_base_reports_it():
    base = _g()
    frag = read(HEAD + '\n# ada [Person]\n* nickname: Ada\n').graph
    assert [str(f.node) for f in _found(frag, against=base)] == ['http://e.o/ada']


def test_cli_warns_and_strict_fails(tmp_path, capsys):
    from onya.cli.onya import validate as cli_validate
    (tmp_path / 'a.onya').write_text(HEAD + SHAPES + '\n# ada [Person]\n* nickname: Ada\n')
    cli_validate(str(tmp_path))  # a warning: passes
    assert 'warning deprecated' in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli_validate(str(tmp_path), strict=True)
    assert e.value.code == 2
