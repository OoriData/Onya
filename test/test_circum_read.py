# -*- coding: utf-8 -*-
# test/test_circum_read.py
'''
The read side of `onya.circum`: sidecars declared in the graph, `augment` (tables -> graph view), `strip`, `emit`
(graph -> tables) and `onya catalog`. The sidecar is a SQLite table, so nothing here needs a live service.

    pytest -s test/test_circum_read.py
'''

import io
import sqlite3

import pytest

from onya.circum import (CircumAccessDenied, CircumDerivedError, CircumError, Edge, Node, Registry, Text, augment,
                         catalog, check_persistable, emit, is_view, strip, view_findings)
from onya.digest import digest
from onya.serial.literate import read, write
from onya.shape import validate
from onya.store.filesystem import FileStore

NS = 'http://e.o/'
COUNSELLED_BY = NS + 'counselledBy'
GPA = NS + 'gpa'
METHOD, ASOF = 'http://purl.org/onya/vocab/method', 'http://purl.org/onya/vocab/asOf'

DOC = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# Student [@Class]
# Person [@Class]

# counselledBy [@Property]
* @appliesTo -> Student
* @range -> Person
* @cardinality: 1
* @circumQuery -> counsellor-assignments
  * @queryDetail: counsellor_for_students

# gpa [@Property]
* @appliesTo -> Student
* @as: number
* @circumQuery -> counsellor-assignments

# counsellor-assignments [@Sidecar]
* @label: Counsellor assignments
* @system -> onya-uni-db
* @table: counsellor
* @sensitivity: internal
* @retention: life of the enrolment plus seven years

# onya-uni-db [@System]
* @label: University database

# chuks [Student]
* name: Chukwuemeka Okafor
* knows -> ify

# ify [Person]
* name: Ifeoma Obasi

# dede [Student]
* name: Desdemona Eze
'''


# counselledBy pointing at something that is no @Sidecar
NOT_A_SIDECAR = DOC.replace('@circumQuery -> counsellor-assignments\n  * @queryDetail',
                            '@circumQuery -> onya-uni-db\n  * @queryDetail')


@pytest.fixture
def g():
    return read(DOC).graph


class Uni:
    '''A university database: a SQLite table the resolvers read, and the writer writes.'''
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE counsellor (iri TEXT PRIMARY KEY, counsellor_iri TEXT, display_name TEXT, '
                          'gpa TEXT, updated TEXT)')
        self.queries = []  # one entry per resolver call: the batch it was given

    def add(self, iri, counsellor_iri, display_name, gpa=None, updated='2026-10-29T14:03:00Z'):
        self.conn.execute('INSERT INTO counsellor VALUES (?, ?, ?, ?, ?)',
                          (iri, counsellor_iri, display_name, gpa, updated))

    def registry(self, policy=None):
        reg = Registry(policy=policy)

        @reg.resolver(COUNSELLED_BY)
        async def counselled_by(subjects, ctx):
            assert ctx.detail == 'counsellor_for_students' and ctx.sidecar.table == 'counsellor'
            self.queries.append(('counselledBy', list(subjects)))
            marks = ', '.join('?' * len(subjects))
            found = self.conn.execute(f'SELECT iri, counsellor_iri, display_name, updated FROM counsellor '
                                      f'WHERE iri IN ({marks})', subjects).fetchall()
            return {iri: [Edge(c, node=Node(('Person',), {NS + 'name': name}), as_of=when)]
                    for iri, c, name, when in found}

        @reg.resolver(GPA)
        def gpa(subjects, ctx):  # a plain function works too
            self.queries.append(('gpa', list(subjects)))
            marks = ', '.join('?' * len(subjects))
            found = self.conn.execute(f'SELECT iri, gpa FROM counsellor WHERE gpa IS NOT NULL AND iri IN ({marks})',
                                      subjects).fetchall()
            return {iri: [Text(v)] for iri, v in found}

        @reg.writer(COUNSELLED_BY)
        async def put_counselled_by(rows, ctx):
            for subject, items in rows.items():
                for e in items:
                    name = (e.node.props.get(NS + 'name') or [None])[0] if e.node else None
                    self.conn.execute('INSERT INTO counsellor (iri, counsellor_iri, display_name) VALUES (?, ?, ?) '
                                      'ON CONFLICT (iri) DO UPDATE SET counsellor_iri = excluded.counsellor_iri',
                                      (subject, e.target, name))
        return reg


@pytest.fixture
def uni():
    u = Uni()
    u.add(NS + 'chuks', NS + 'adat-okon', 'Adat Okon', gpa='3.4')
    return u


@pytest.mark.asyncio
async def test_augment_adds_marked_assertions_and_creates_the_target(g, uni):
    view = await augment(g, registry=uni.registry(), now='2026-11-06T00:00:00Z')
    chuks, adat = view[NS + 'chuks'], view[NS + 'adat-okon']
    (e,) = chuks.getedge(COUNSELLED_BY)
    assert e.target is adat
    assert [m.target.id for m in e.getedge(METHOD)] == [
        NS + 'counsellor-assignments']
    assert e.any_prop_value(ASOF) == '2026-10-29T14:03:00Z'  # the row's own time
    assert adat.values(NS + 'name') == ['Adat Okon']
    assert str(next(iter(adat.types))) == NS + 'Person'
    assert chuks.values(GPA) == ['3.4']
    assert next(iter(chuks.getprop(GPA))).any_prop_value(ASOF) == '2026-11-06T00:00:00Z'
    assert not list(g[NS + 'chuks'].getedge(COUNSELLED_BY))  # the pure graph is untouched
    assert NS + 'adat-okon' not in g.nodes


@pytest.mark.asyncio
async def test_strip_restores_the_graph_exactly(g, uni):
    view = await augment(g, registry=uni.registry())
    assert digest(view) != digest(g)
    assert digest(strip(view)) == digest(g)
    assert NS + 'adat-okon' not in strip(view).nodes


@pytest.mark.asyncio
async def test_a_target_already_in_the_graph_is_not_retyped_and_survives_strip(g, uni):
    g = read(DOC + '\n# adat-okon [Person]\n* name: Adat Okon\n* office: B12\n').graph
    view = await augment(g, registry=uni.registry())
    adat = view[NS + 'adat-okon']
    assert sorted(adat.values(NS + 'name')) == ['Adat Okon']  # the authored value, not duplicated
    assert not list(adat.getedge(METHOD))  # not a created node
    assert digest(strip(view)) == digest(g)
    assert strip(view)[NS + 'adat-okon'].values(NS + 'office') == ['B12']


@pytest.mark.asyncio
async def test_one_batch_per_property_however_many_subjects(g, uni):
    uni.add(NS + 'dede', NS + 'adat-okon', 'Adat Okon')
    await augment(g, registry=uni.registry())
    assert uni.queries == [('counselledBy', [NS + 'chuks', NS + 'dede']), ('gpa', [NS + 'chuks', NS + 'dede'])]


@pytest.mark.asyncio
async def test_ids_limits_the_subjects(g, uni):
    uni.add(NS + 'dede', NS + 'adat-okon', 'Adat Okon')
    view = await augment(g, registry=uni.registry(), ids=[NS + 'chuks'])
    assert uni.queries[0] == ('counselledBy', [NS + 'chuks'])
    assert not list(view[NS + 'dede'].getedge(COUNSELLED_BY))


@pytest.mark.asyncio
async def test_only_nodes_a_property_applies_to_are_asked_about(g, uni):
    await augment(g, registry=uni.registry())
    assert NS + 'ify' not in uni.queries[0][1]  # a Person, not a Student


@pytest.mark.asyncio
async def test_policy_refuses_before_any_resolver_runs(g, uni):
    reg = uni.registry(policy=lambda viewer, sensitivity: sensitivity == 'public')
    with pytest.raises(CircumAccessDenied) as e:
        await augment(g, registry=reg, viewer='intern')
    assert 'counsellor-assignments' in str(e.value) and 'counselledBy' in str(e.value)
    assert uni.queries == []


@pytest.mark.asyncio
async def test_policy_that_allows_lets_the_viewer_through(g, uni):
    reg = uni.registry(policy=lambda viewer, sensitivity: viewer == 'staff' or sensitivity == 'public')
    assert list((await augment(g, registry=reg, viewer='staff'))[NS + 'chuks'].getedge(COUNSELLED_BY))


@pytest.mark.asyncio
async def test_a_resolver_that_raises_fails_augment(g, uni):
    reg = uni.registry()

    @reg.resolver(GPA)
    async def broken(subjects, ctx):
        raise RuntimeError('database is down')

    with pytest.raises(CircumError, match='gpa.*counsellor-assignments.*database is down'):
        await augment(g, registry=reg)


@pytest.mark.asyncio
async def test_on_error_finding_returns_a_view_and_the_finding(g, uni):
    reg = uni.registry()

    @reg.resolver(GPA)
    async def broken(subjects, ctx):
        raise RuntimeError('database is down')

    with pytest.warns(UserWarning, match='read back'):
        view = await augment(g, registry=reg, on_error='finding')
    assert list(view[NS + 'chuks'].getedge(COUNSELLED_BY))  # the other property still arrived
    (f,) = view_findings(view)
    assert f.label == GPA and 'database is down' in f.detail
    with pytest.raises(ValueError):
        await augment(g, registry=reg, on_error='ignore')


@pytest.mark.asyncio
async def test_a_missing_resolver_is_an_error_naming_the_property(g, uni):
    reg = Registry()
    with pytest.raises(CircumError, match='no resolver.*counselledBy'):
        await augment(g, registry=reg)


@pytest.mark.asyncio
async def test_a_resolver_returning_unrequested_rows_is_refused(g, uni):
    reg = uni.registry()

    @reg.resolver(GPA)
    async def greedy(subjects, ctx):
        return {NS + 'someone-else': [Text('4.0')]}

    with pytest.raises(CircumError, match='not asked about'):
        await augment(g, registry=reg)


@pytest.mark.asyncio
async def test_an_absent_row_is_a_cardinality_finding_on_the_view(g, uni):
    view = await augment(g, registry=uni.registry())
    found = [f for f in validate(view).findings if f.kind == 'cardinality']
    assert [str(f.node) for f in found] == [NS + 'dede']  # chuks has a counsellor, dede has no row
    # the pure graph is not incomplete: the value was never meant to be in it
    assert not [f for f in validate(g).findings if f.kind == 'cardinality']


@pytest.mark.asyncio
async def test_a_view_says_it_is_one_so_it_survives_writing_out(g, uni):
    view = await augment(g, registry=uni.registry())
    assert is_view(view) and not is_view(g)
    out = io.StringIO()
    write(view, out)
    again = read(out.getvalue()).graph  # text only: no Python-side marker can come along
    assert is_view(again)
    assert [str(f.node) for f in validate(again).findings if f.kind == 'cardinality'] == [NS + 'dede']
    with pytest.raises(CircumDerivedError):
        check_persistable(again)
    assert digest(strip(again)) == digest(g)


@pytest.mark.asyncio
async def test_a_view_with_no_rows_is_still_a_view(g):
    empty = Registry()
    for label in (COUNSELLED_BY, NS + 'gpa'):
        empty.resolver(label)(lambda subjects, ctx: {})
    view = await augment(g, registry=empty)
    assert is_view(view)
    assert sorted(str(f.node) for f in validate(view).findings if f.kind == 'cardinality') == \
        [NS + 'chuks', NS + 'dede']
    with pytest.raises(CircumDerivedError):
        check_persistable(view)


@pytest.mark.asyncio
async def test_augmenting_a_view_again_leaves_one_marker(g, uni):
    twice = await augment(await augment(g, registry=uni.registry()), registry=uni.registry())
    assert digest(strip(twice)) == digest(g)
    sc = next(n for n in twice.nodes.values() if str(n.id).endswith('counsellor-assignments'))
    assert len(list(sc.getprop('@asOf'))) == 1


@pytest.mark.asyncio
async def test_only_nodes_that_were_asked_about_can_be_incomplete(g, uni):
    def missing(view):
        return [str(f.node) for f in validate(view).findings if f.kind == 'cardinality']

    # dede has no row, but a view limited to chuks never looked for one
    assert missing(await augment(g, registry=uni.registry(), ids=[NS + 'chuks'])) == []
    # asked about dede and found nothing: now it is a gap
    assert missing(await augment(g, registry=uni.registry(), ids=[NS + 'dede'])) == [NS + 'dede']
    view = await augment(g, registry=uni.registry(), ids=[NS + 'chuks'])
    assert digest(strip(view)) == digest(g)  # the per-node marks go too


@pytest.mark.asyncio
async def test_a_failed_resolver_does_not_mark_its_nodes_as_asked(g, uni):
    reg = uni.registry()

    @reg.resolver(COUNSELLED_BY)
    def broken(subjects, ctx):
        raise RuntimeError('database is down')

    with pytest.warns(UserWarning, match='written out and read back'):  # gpa succeeded in the same sidecar
        view = await augment(g, registry=reg, on_error='finding')
    assert view_findings(view)
    # no "expected 1, found 0" for students we failed to read: the failure is the finding
    assert not [f for f in validate(view).findings if f.kind == 'cardinality']


@pytest.mark.asyncio
async def test_one_warning_names_every_affected_property(uni):
    doc = DOC.replace('# counsellor-assignments [@Sidecar]', '# tutor [@Property]\n* @appliesTo -> Student\n'
                      '* @circumQuery -> counsellor-assignments\n\n# counsellor-assignments [@Sidecar]')
    reg = uni.registry()
    for label in (COUNSELLED_BY, NS + 'tutor'):  # two fail, gpa succeeds
        reg.resolver(label)(lambda subjects, ctx: 1 / 0)
    with pytest.warns(UserWarning) as caught:
        await augment(read(doc).graph, registry=reg, on_error='finding')
    (w,) = [w for w in caught if 'read back' in str(w.message)]  # one warning, not one per property
    assert COUNSELLED_BY in str(w.message) and NS + 'tutor' in str(w.message) and GPA not in str(w.message)


@pytest.mark.asyncio
async def test_no_warning_when_a_failed_resolver_has_no_sibling_in_its_sidecar(g, uni, recwarn):
    reg = Registry()
    reg.resolver(COUNSELLED_BY)(lambda subjects, ctx: {})

    @reg.resolver(GPA)
    def broken(subjects, ctx):
        raise RuntimeError('database is down')

    # both fail: nothing in the sidecar was marked as asked about, so a round trip loses nothing
    reg.resolver(COUNSELLED_BY)(broken)
    await augment(g, registry=reg, on_error='finding')
    assert not [w for w in recwarn if 'read back' in str(w.message)]


@pytest.mark.asyncio
async def test_a_view_in_a_separate_declarations_graph(uni):
    shapes = read(DOC).graph
    data = read(DOC.split('# Student [@Class]')[0] + '\n# chuks [Student]\n* name: Chuks\n').graph
    view = await augment(data, registry=uni.registry(), shapes=shapes)
    assert list(view[NS + 'chuks'].getedge(COUNSELLED_BY))
    assert digest(strip(view, shapes=shapes)) == digest(data)
    assert digest(strip(view)) == digest(data)  # the view itself remembers its sidecars


@pytest.mark.asyncio
async def test_a_view_is_not_persisted(g, uni, tmp_path):
    view = await augment(g, registry=uni.registry())
    with pytest.raises(CircumDerivedError, match='strip'):
        check_persistable(view)
    async with FileStore(tmp_path) as store:
        with pytest.raises(CircumDerivedError):
            await store.put('http://e.o/doc', view)
        await store.put('http://e.o/doc', strip(view))  # the stripped graph is fine


@pytest.mark.asyncio
async def test_the_declarations_must_be_sound(g, uni):
    bad = read(NOT_A_SIDECAR).graph
    with pytest.raises(CircumError, match='not declared as a @Sidecar'):
        await augment(bad, registry=uni.registry())
    assert any(f.kind == 'circum' for f in validate(bad).findings)  # `onya validate` says so too


def test_catalog_lists_sidecars_with_what_they_hold(g):
    (sc,) = catalog(g)
    assert (sc.label, sc.table, sc.sensitivity) == ('Counsellor assignments', 'counsellor', 'internal')
    assert str(sc.system) == NS + 'onya-uni-db'
    assert [str(p.label) for p in sc.holds] == [COUNSELLED_BY, GPA]
    assert sc.holds[0].detail == 'counsellor_for_students'


@pytest.mark.asyncio
async def test_emit_moves_circum_assertions_into_the_sidecar(uni):
    g = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon\n\n# adat-okon [Person]\n* name: Adat Okon\n').graph
    report = await emit(g, touched=[NS + 'dede'], registry=uni.registry())
    assert report.moved == [(NS + 'counsellor-assignments', NS + 'dede', COUNSELLED_BY)]
    assert not list(g[NS + 'dede'].getedge(COUNSELLED_BY))
    assert uni.conn.execute('SELECT counsellor_iri, iri FROM counsellor WHERE iri = ?',
                            (NS + 'dede',)).fetchone() == (NS + 'adat-okon', NS + 'dede')
    # idempotent: nothing left to move
    again = await emit(g, touched=[NS + 'dede'], registry=uni.registry())
    assert again.moved == [] and again.review == []


@pytest.mark.asyncio
async def test_emit_leaves_identified_and_nested_assertions_for_review(uni):
    g = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon [=claim]\n\n# adat-okon [Person]\n').graph
    report = await emit(g, registry=uni.registry())
    assert report.moved == [] and 'id or nested' in report.review[0]
    assert list(g[NS + 'dede'].getedge(COUNSELLED_BY))

    h = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon\n  * note: promised\n\n'
             '# adat-okon [Person]\n').graph
    assert (await emit(h, registry=uni.registry())).moved == []


@pytest.mark.asyncio
async def test_emit_failing_writer_leaves_the_graph_unchanged(uni):
    g = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon\n\n# adat-okon [Person]\n').graph
    reg = uni.registry()

    @reg.writer(COUNSELLED_BY)
    async def broken(rows, ctx):
        raise RuntimeError('disk full')

    before = digest(g)
    with pytest.raises(CircumError, match='writer failed.*disk full'):
        await emit(g, registry=reg)
    assert digest(g) == before


@pytest.mark.asyncio
async def test_emit_refuses_without_a_writer_or_without_access(uni):
    g = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon\n\n# adat-okon [Person]\n').graph
    reg = uni.registry()
    del reg.writers[COUNSELLED_BY]
    with pytest.raises(CircumError, match='no writer'):
        await emit(g, registry=reg)
    with pytest.raises(CircumAccessDenied):
        await emit(g, registry=uni.registry(policy=lambda v, s: False))
    assert list(g[NS + 'dede'].getedge(COUNSELLED_BY))


@pytest.mark.asyncio
async def test_emit_ignores_what_came_from_a_sidecar(g, uni):
    view = await augment(g, registry=uni.registry())
    assert (await emit(view, registry=uni.registry())).moved == []  # nothing authored to move
    assert list(view[NS + 'chuks'].getedge(COUNSELLED_BY))


@pytest.mark.asyncio
async def test_emit_then_augment_round_trips(uni):
    g = read(DOC + '\n# dede [Student]\n* counselledBy -> adat-okon\n\n# adat-okon [Person]\n* name: Adat Okon\n').graph
    await emit(g, registry=uni.registry())
    view = await augment(g, registry=uni.registry())
    (e,) = view[NS + 'dede'].getedge(COUNSELLED_BY)
    assert e.target.id == NS + 'adat-okon'


def test_cli_catalog_lists_sidecars_and_what_they_hold(tmp_path, capsys):
    from onya.cli.onya import catalog as cli_catalog
    f = tmp_path / 'kg.onya'
    f.write_text(DOC, encoding='utf-8')
    cli_catalog(str(f))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == ('counsellor-assignments  Counsellor assignments  system: onya-uni-db  table: counsellor  '
                      'sensitivity: internal')
    assert out[1:] == ['  holds: counselledBy (Student -> Person)', '  holds: gpa (Student)']


def test_cli_catalog_exits_2_on_a_bad_declaration(tmp_path, capsys):
    from onya.cli.onya import catalog as cli_catalog
    f = tmp_path / 'kg.onya'
    f.write_text(NOT_A_SIDECAR.replace('onya-uni-db', 'ify'), encoding='utf-8')
    with pytest.raises(SystemExit) as e:
        cli_catalog(str(f))
    assert e.value.code == 2 and 'not declared as a @Sidecar' in capsys.readouterr().err


@pytest.mark.asyncio
async def test_sqlite_store_refuses_a_view_too(g, uni, tmp_path):
    from onya.store.sqlite import SqliteStore
    view = await augment(g, registry=uni.registry())
    async with await SqliteStore.from_url(f'sqlite:{tmp_path / "s.db"}') as store:
        with pytest.raises(CircumDerivedError):
            await store.put('http://e.o/doc', view)
        await store.put('http://e.o/doc', strip(view))
