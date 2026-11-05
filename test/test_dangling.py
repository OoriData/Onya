# -*- coding: utf-8 -*-
# test/test_dangling.py
'''
Dangling edge targets (#60): an edge to an id that nothing ever declared is a forward reference
that stayed forward, usually a typo. The parser tells declared nodes from merely-referenced ones;
the check is opt-in (`on_dangling`) since external IRIs are legitimately never declared.

    pytest -s test/test_dangling.py
'''

import pytest

from onya.graph import graph
from onya.serial.literate import DanglingTargetError, read, read_many

HEAD = '''# @docheader

* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://schema.org/

'''
ORCID = 'https://orcid.org/0000-0002-1825-0097'
TEXT = HEAD + f'''# A [Person]

* knows -> Typo
* author -> <{ORCID}>
* knows -> B

# B [Person]

* name: B
'''
TYPO = 'http://e.o/Typo'


def test_typo_and_external_are_dangling_declared_target_is_not():
    g = graph()
    r = read(TEXT, g)
    assert {str(d.target) for d in r.dangling} == {TYPO, ORCID}
    assert {str(i) for i in g.dangling()} == {TYPO, ORCID}
    assert not g['http://e.o/Typo'].declared and g['http://e.o/B'].declared


def test_dangling_entry_names_source_label_target():
    r = read(TEXT, graph())
    d = next(d for d in r.dangling if str(d.target) == TYPO)
    assert (str(d.source), str(d.label)) == ('http://e.o/A', 'https://schema.org/knows')
    assert str(d) == 'http://e.o/A --https://schema.org/knows--> http://e.o/Typo (location not tracked)'


def test_forward_reference_within_one_document_is_declared():
    g = graph()
    r = read(HEAD + '# A\n\n* knows -> B\n\n# B\n\n* name: B\n', g)
    assert r.dangling == [] and g.dangling() == set()


def test_nested_edge_reports_owning_node():
    r = read(HEAD + '# A\n\n* knows -> B\n  * via -> Nowhere\n\n# B\n\n* name: B\n', graph())
    (d,) = r.dangling
    assert str(d.target) == 'http://e.o/Nowhere' and str(d.source) == 'http://e.o/A'


def test_edge_to_assertion_id_is_never_dangling():
    g = graph()
    r = read(HEAD + '# A\n\n* knows -> B [=ab]\n\n# B\n\n* name: B\n\n# C\n\n* confirms -> ab\n', g)
    assert r.dangling == [] and g.dangling() == set()


@pytest.mark.parametrize('allow', [
    'https://orcid.org/', ['https://orcid.org/', 'http://other/'], lambda i: str(i).startswith('https://orcid.org/'),
])
def test_allow_forms(allow):
    g = graph()
    r = read(TEXT, g, allow=allow)
    assert {str(d.target) for d in r.dangling} == {TYPO}
    assert {str(i) for i in g.dangling(allow=allow)} == {TYPO}


def test_empty_block_declares_the_node():
    '''An empty block is still a block: it declares, whichever order it arrives in.'''
    g = graph()
    with pytest.warns(UserWarning, match='empty'):
        read(HEAD + '# A\n\n* knows -> E\n\n# E\n', g)
    assert g.dangling() == set()
    g2 = graph()
    read(HEAD + '# A\n\n* knows -> E\n', g2)
    assert g2.dangling() == {g2['http://e.o/E'].id}
    with pytest.warns(UserWarning, match='empty'):
        read(HEAD + '# E\n', g2)
    assert g2.dangling() == set()


def test_later_read_into_same_graph_declares_it():
    g = graph()
    read(HEAD + '# A\n\n* knows -> B\n', g)
    assert len(g.dangling()) == 1
    r = read(HEAD + '# B [Person]\n', g)
    assert g.dangling() == set() and r.dangling == []


def test_second_read_referencing_an_old_stub_reports_it_again():
    g = graph()
    read(HEAD + '# A\n\n* knows -> Typo\n', g)
    r = read(HEAD + '# C\n\n* knows -> Typo\n', g)
    assert [str(d.source) for d in r.dangling] == ['http://e.o/C']


def test_api_calls_declare():
    g = graph()
    read(HEAD + '# A\n\n* knows -> B\n* knows -> C\n* knows -> D\n', g)
    g['http://e.o/B'].add_property('name', 'B')
    g['http://e.o/C'].types.add('http://e.o/Person')
    g.node('http://e.o/E')  # created directly, never a stub
    assert {str(i) for i in g.dangling()} == {'http://e.o/D'}


def test_union_keeps_the_distinction():
    a, b = graph(), graph()
    read(HEAD + '# A\n\n* knows -> B\n* knows -> Typo\n', a)
    read(HEAD + '# B [Person]\n', b)
    a.union(b)
    assert {str(i) for i in a.dangling()} == {TYPO}  # declared by `b`, so B is resolved
    c, d = graph(), graph()
    read(HEAD + '# A\n\n* knows -> Typo\n', c)
    read(HEAD + '# X\n\n* knows -> Typo\n', d)
    c.union(d)
    assert {str(i) for i in c.dangling()} == {TYPO}  # undeclared on both sides stays undeclared


def test_copy_and_subgraph_carry_it():
    g = graph()
    read(TEXT, g)
    assert g.copy().dangling() == g.dangling()
    sub = g.subgraph(['http://e.o/A'], hops=0)
    # B is declared in the original but outside the neighborhood: bare, so undeclared in the copy
    assert {str(i) for i in sub.dangling()} == {TYPO, ORCID, 'http://e.o/B'}


def test_merge_does_not_change_the_answer():
    g = graph()
    read(HEAD + '# A\n\n* knows -> Typo\n* knows -> Typo\n', g)
    g.merge()
    assert {str(i) for i in g.dangling()} == {TYPO}
    r = read(HEAD + '# A\n\n* knows -> Typo\n* knows -> Typo\n', graph(), merge=True)
    assert len(r.dangling) == 2  # each reference in the text counts


def test_default_ignores_warn_warns_error_raises():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        read(TEXT, graph())  # default: silent
    with pytest.warns(UserWarning, match='never declared'):
        read(TEXT, graph(), on_dangling='warn')
    with pytest.raises(DanglingTargetError, match='Typo') as ei:
        read(TEXT, graph(), on_dangling='error')
    assert len(ei.value.dangling) == 2
    assert isinstance(ei.value, ValueError)


def test_error_is_quiet_when_everything_is_allowed_or_declared():
    read(TEXT, graph(), on_dangling='error', allow=['https://orcid.org/', 'http://e.o/Typo'])
    read(HEAD + '# A\n\n* knows -> B\n\n# B\n\n* name: B\n', graph(), on_dangling='error')


def test_bad_on_dangling_value():
    with pytest.raises(ValueError, match='on_dangling'):
        read(TEXT, graph(), on_dangling='loud')


def test_read_many_checks_after_all_files(tmp_path):
    (tmp_path / 'a.onya').write_text(HEAD + '# A\n\n* knows -> B\n* knows -> Typo\n')
    (tmp_path / 'b.onya').write_text(HEAD + '# B [Person]\n')
    res = read_many(str(tmp_path), on_dangling='ignore')
    assert {str(d.target) for d in res.dangling} == {TYPO}  # B arrived in a later file
    assert [str(d.target) for r in res.results.values() for d in r.dangling] == [TYPO]
    with pytest.raises(DanglingTargetError, match='Typo') as ei:
        read_many(str(tmp_path), on_dangling='error')
    assert len(ei.value.dangling) == 1  # not B
    assert read_many(str(tmp_path), on_dangling='error', allow='http://e.o/Typo').dangling == []


def test_write_collects_placeholders_without_changing_output():
    from io import StringIO

    from onya.serial.literate import write
    g = graph()
    read(TEXT, g)
    plain, seen = StringIO(), set()
    write(g, plain, nodebase='http://e.o/', schema='https://schema.org/')
    collected = StringIO()
    write(g, collected, nodebase='http://e.o/', schema='https://schema.org/', placeholders=seen)
    assert collected.getvalue() == plain.getvalue()  # the set is a report, not a filter
    assert {str(i) for i in seen} == {TYPO, ORCID}  # B is declared, A has content


def test_write_placeholders_empty_for_a_fully_declared_graph():
    from io import StringIO

    from onya.serial.literate import write
    g = graph()
    read(HEAD + '# A\n\n* knows -> B\n\n# B\n\n* name: B\n', g)
    seen = set()
    write(g, StringIO(), nodebase='http://e.o/', placeholders=seen)
    assert seen == set()


# --- CLI ---------------------------------------------------------------------------

def _cli(tmp_path, *texts, **kw):
    from onya.cli.onya import convert
    for i, t in enumerate(texts):
        (tmp_path / f'f{i}.onya').write_text(t)
    return convert(str(tmp_path), mermaid=True, out=str(tmp_path / 'o.mmd'), **kw)


def test_cli_default_ignores(tmp_path):
    _cli(tmp_path, TEXT)


def test_cli_error_exits_nonzero_and_names_the_edge(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        _cli(tmp_path, TEXT, on_dangling='error')
    assert ei.value.code == 2
    assert 'Typo' in capsys.readouterr().err


def test_cli_judges_after_all_files_and_honors_allow(tmp_path):
    a = HEAD + '# A\n\n* knows -> B\n* author -> <https://orcid.org/x>\n'
    b = HEAD + '# B [Person]\n'
    _cli(tmp_path, a, b, on_dangling='error', allow='https://orcid.org/')
    _cli(tmp_path, a, b, on_dangling='error', allow='http://nope/,https://orcid.org/')  # comma-separated
    with pytest.raises(SystemExit):
        _cli(tmp_path, a, b, on_dangling='error')  # the ORCID target, un-allowed


def test_cli_warn_and_bad_value(tmp_path):
    with pytest.warns(UserWarning, match='never declared'):
        _cli(tmp_path, TEXT, on_dangling='warn')
    with pytest.raises(ValueError, match='on_dangling'):
        _cli(tmp_path, TEXT, on_dangling='loud')


def test_subgraph_frontier_is_undeclared_in_the_copy_only():
    '''The documented surprise: Cy is declared in the graph but a bare neighbor in a 1-hop copy.'''
    g = graph()
    read(HEAD + '# Ada\n\n* knows -> Ben\n\n# Ben\n\n* knows -> Cy\n\n# Cy\n\n* name: Cy\n', g)
    cy = 'http://e.o/Cy'
    assert g.dangling() == set() and g[cy].declared
    one = g.subgraph(['http://e.o/Ada'], hops=1)
    assert {str(i) for i in one.dangling()} == {cy}  # cut off at the edge of the neighborhood
    assert g.subgraph(['http://e.o/Ada'], hops=2).dangling() == set()  # reached, so declared again
