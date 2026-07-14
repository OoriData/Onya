# -*- coding: utf-8 -*-
# test/store/test_store_guards.py
'''
Architectural guards, each run in a fresh subprocess so module-import state is pristine:

- **Layering**: importing the core (``onya.graph``, ``onya.serial.literate``, ``onya.interp``)
  must not drag in anything under ``onya.store`` — storage is a peripheral, not an organ.
- **Lazy PostgreSQL dependency**: with asyncpg absent, ``file:`` and ``sqlite:`` still work;
  ``postgresql:`` raises an instructive ``ImportError`` pointing at the extra.

    pytest -s test/store/test_store_guards.py
'''

import subprocess
import sys
import textwrap


def _run(code: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, '-c', textwrap.dedent(code), *args],
                          capture_output=True, text=True)


def test_core_does_not_import_store():
    code = '''
        import sys
        import onya.graph
        import onya.serial.literate
        import onya.interp
        leaked = sorted(m for m in sys.modules if m == 'onya.store' or m.startswith('onya.store.'))
        assert not leaked, f'core import leaked store modules: {leaked}'
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_core_does_not_import_serial_nx():
    '''The networkx projection is an analytics peripheral like the store: the core must not
    drag it in.'''
    code = '''
        import sys
        import onya.graph
        import onya.serial.literate
        import onya.interp
        leaked = sorted(m for m in sys.modules if m == 'onya.serial.nx')
        assert not leaked, f'core import leaked serial.nx: {leaked}'
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_serial_nx_does_not_import_store_or_networkx_eagerly():
    '''onya.serial.nx imports the core only; networkx is lazy (import must not fail without it),
    and it never reaches into onya.store.'''
    code = '''
        import sys
        sys.modules['networkx'] = None  # make `import networkx` raise ImportError
        import onya.serial.nx  # must import fine: networkx is lazy
        leaked = sorted(m for m in sys.modules if m == 'onya.store' or m.startswith('onya.store.'))
        assert not leaked, f'serial.nx leaked store modules: {leaked}'
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_lazy_networkx_and_instructive_import_error():
    '''With networkx absent, to_networkx raises an ImportError naming the extra.'''
    code = '''
        import sys
        sys.modules['networkx'] = None  # make `import networkx` raise ImportError
        from onya.graph import graph
        from onya.serial import nx
        try:
            nx.to_networkx(graph())
        except ImportError as e:
            assert 'onya[nx]' in str(e), str(e)
            print('IMPORTERROR_OK')
        else:
            print('NO_IMPORTERROR'); sys.exit(2)
    '''
    r = _run(code)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert 'IMPORTERROR_OK' in r.stdout


def test_lazy_asyncpg_and_instructive_import_error(tmp_path):
    code = '''
        import sys, asyncio
        sys.modules['asyncpg'] = None  # make `import asyncpg` raise ImportError
        from onya.store import connect

        async def main():
            async with await connect('file:' + sys.argv[1]):
                pass
            async with await connect('sqlite:' + sys.argv[2]):
                pass
            try:
                await connect('postgresql://user:pass@localhost:5432/db')
            except ImportError as e:
                assert 'onya[postgres]' in str(e), str(e)
                print('IMPORTERROR_OK')
                return
            print('NO_IMPORTERROR')
            sys.exit(2)

        asyncio.run(main())
    '''
    r = _run(code, f'{tmp_path}/graphs', f'{tmp_path}/app.db')
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert 'IMPORTERROR_OK' in r.stdout
