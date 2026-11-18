# -*- coding: utf-8 -*-
# test/store/test_store_transient.py
'''A store refuses a graph marked `@transient`: a redacted copy, or a circum view, however it got that way (#84).'''

import pytest

from onya.circum import CircumDerivedError
from onya.graph import graph
from onya.redact import redact
from onya.serial.literate import read
from onya.transient import TransientError

SRC = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: http://e.o/

# salary [@Property]
* @sensitivity: partner

# ada [Person]
* name: Ada
* salary: 90000
'''


def _redacted():
    g = graph()
    read(SRC, g)
    return redact(g, 'v', lambda viewer, sensitivity: False)


async def test_put_refuses_a_redacted_graph_and_writes_nothing(store):
    with pytest.raises(TransientError, match='http://e.o/ada'):
        await store.put('http://e.o/doc', _redacted())
    assert not await store.exists('http://e.o/doc') if hasattr(store, 'exists') else True
    g = graph()
    read(SRC, g)
    await store.put('http://e.o/doc', g)  # the original is fine
    with pytest.raises(TransientError):
        await store.put('http://e.o/doc', _redacted(), merge=False)  # replacing it with the copy is refused too
    got = await store.get('http://e.o/doc')
    assert any(str(p.label).endswith('salary') for p in got.nodes['http://e.o/ada'].properties)  # still whole


async def test_a_hand_marked_graph_is_refused(store):
    g = graph()
    read(SRC + '\n# bo [Person]\n* @transient: true\n    * @reason: scratch\n', g)
    with pytest.raises(TransientError, match='scratch'):
        await store.put('http://e.o/doc', g)


def test_a_circum_view_error_is_also_a_transient_error():
    assert issubclass(CircumDerivedError, TransientError)  # one `except TransientError` catches both
