# -*- coding: utf-8 -*-
# test/store/test_store_digest.py
'''
Store parity: what a backend gives back by `get` has the same content digest as what was `put`
(and as a plain `read` of the same text), on every backend.
'''

import pytest

from onya.digest import digest
from onya.serial.literate import read

DOC = '''# @docheader
* @document: http://e.o/doc
* @nodebase: http://e.o/
* @schema: https://s.org/

# A [Person]
* name: Ada
  * @as: text
* email: a@e.o
* email: ada@e.o
  * @ordering: 2
* knows -> B [=k1]
  * since: 1842
    * @as: integer

# B [Person]
* name: Babbage
'''


@pytest.mark.asyncio
async def test_get_has_the_digest_of_what_was_put(store):
    g = read(DOC).graph
    await store.put('http://e.o/doc', g)
    assert digest(await store.get('http://e.o/doc')) == digest(read(DOC).graph)
