# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# test/test_read_many.py
'''
Multi-file reading (#54): `read_many`, `expand_paths`, and the CLI's directory expansion,
which must pick up `*.onya.md` as well as `*.onya`.

    pytest -s test/test_read_many.py
'''

import pytest

from onya.cli.onya import convert
from onya.serial.literate import LITERATE_SUFFIXES, expand_paths, read_many

HEAD = '# @docheader\n* @document: http://example.org/{doc}\n* @nodebase: http://example.org/kg/\n* @schema: https://schema.org/\n\n'
PEOPLE = HEAD.format(doc='people') + '# chuks [Person]\n* name: Chukwuemeka\n* knows -> ify\n'
ORGS = HEAD.format(doc='orgs') + '# ify [Person]\n* name: Ifeoma\n'
ORGS_DUP = HEAD.format(doc='more') + '# ify [Person]\n* name: Ifeoma\n'


@pytest.fixture
def kg(tmp_path):
    '''A KG split over both suffixes, one file in a subdirectory.'''
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'a.onya.md').write_text(PEOPLE, encoding='utf-8')
    (tmp_path / 'sub' / 'b.onya').write_text(ORGS, encoding='utf-8')
    (tmp_path / 'notes.md').write_text('# not onya', encoding='utf-8')  # neither suffix: ignored
    return tmp_path


def test_suffixes():
    assert LITERATE_SUFFIXES == ('.onya', '.onya.md')


def test_directory_expands_both_suffixes_recursively(kg):
    names = [p.name for p in expand_paths(kg)]
    assert names == ['a.onya.md', 'b.onya']  # sorted by path; notes.md excluded


def test_glob_and_plain_file(kg):
    assert [p.name for p in expand_paths(str(kg / '*.onya.md'))] == ['a.onya.md']
    assert expand_paths(kg / 'a.onya.md') == [kg / 'a.onya.md']


def test_read_many_combines_files_into_one_graph(kg):
    r = read_many([kg])
    g = r.graph
    assert set(r.results) == {kg / 'a.onya.md', kg / 'sub' / 'b.onya'}
    assert all(res.doc_iri for res in r.results.values())
    # chuks -> ify resolves to the one `ify` node declared in the other file
    ify = g['http://example.org/kg/ify']
    chuks = g['http://example.org/kg/chuks']
    assert next(chuks.getedge('knows')).target is ify
    assert ify.any_prop_value('name') == 'Ifeoma'


def test_each_file_read_once_even_if_specs_overlap(kg):
    r = read_many([kg, str(kg / '*.onya.md'), kg / 'a.onya.md'])
    assert len(r.results) == 2


def test_merge_runs_once_at_the_end(kg):
    (kg / 'sub' / 'c.onya').write_text(ORGS_DUP, encoding='utf-8')
    unmerged = read_many(kg).graph['http://example.org/kg/ify']
    assert len(unmerged.properties) == 2  # parsing accumulates occurrences
    merged = read_many(kg, merge=True).graph['http://example.org/kg/ify']
    assert len(merged.properties) == 1


def test_populates_a_given_graph(kg):
    first = read_many(kg / 'a.onya.md')
    again = read_many(kg / 'sub' / 'b.onya', first.graph)
    assert again.graph is first.graph
    assert 'http://example.org/kg/ify' in first.graph


def test_unmatched_spec_raises(kg):
    with pytest.raises(FileNotFoundError, match='nothing'):
        read_many([kg, str(kg / 'nothing*.onya')])
    with pytest.raises(FileNotFoundError, match='missing.onya'):
        read_many(kg / 'missing.onya')


def test_empty_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_many(tmp_path)


def test_parse_error_names_the_file(kg):
    bad = kg / 'sub' / 'bad.onya.md'
    bad.write_text(HEAD.format(doc='bad') + '# x [Person\n* name: oops\n', encoding='utf-8')
    with pytest.raises(Exception) as ei:
        read_many(kg)
    assert any(str(bad) in note for note in ei.value.__notes__)


def test_cli_convert_directory_picks_up_onya_md(kg, tmp_path):
    out = tmp_path / 'out.mmd'
    convert(str(kg), mermaid=True, out=str(out))
    mmd = out.read_text(encoding='utf-8')
    assert 'Chukwuemeka' in mmd and 'Ifeoma' in mmd  # a.onya.md AND b.onya
