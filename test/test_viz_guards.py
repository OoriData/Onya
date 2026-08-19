# -*- coding: utf-8 -*-
# test/test_viz_guards.py
'''
Architectural guards for `onya.viz`, each run in a fresh subprocess so module-import state is
pristine:

- **Layering**: importing the core (``onya.graph``, ``onya.serial.literate``, ``onya.interp``)
  must not drag in ``onya.viz`` — visualization is a peripheral, not an organ, mirroring
  ``onya.store``.
- **Lazy networkx dependency**: ``onya.viz.nx`` imports fine without networkx installed (only
  calling ``to_networkx``/``write_back`` needs it), and never reaches into ``onya.store``.
- **Legacy `onya.serial.{mermaid,graphviz,nx}` aliases**: still importable and functionally
  equivalent, but emit ``DeprecationWarning`` pointing at the new ``onya.viz`` home.

    pytest -s test/test_viz_guards.py
'''

import subprocess
import sys
import textwrap

import pytest


def _run(code: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, '-c', textwrap.dedent(code), *args],
                          capture_output=True, text=True)


def test_core_does_not_import_viz():
    code = '''
        import sys
        import onya.graph
        import onya.serial.literate
        import onya.interp
        leaked = sorted(m for m in sys.modules if m == 'onya.viz' or m.startswith('onya.viz.'))
        assert not leaked, f'core import leaked viz modules: {leaked}'
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_viz_nx_does_not_import_store_or_networkx_eagerly():
    '''onya.viz.nx imports the core only; networkx is lazy (import must not fail without it),
    and it never reaches into onya.store.'''
    code = '''
        import sys
        sys.modules['networkx'] = None  # make `import networkx` raise ImportError
        import onya.viz.nx  # must import fine: networkx is lazy
        leaked = sorted(m for m in sys.modules if m == 'onya.store' or m.startswith('onya.store.'))
        assert not leaked, f'viz.nx leaked store modules: {leaked}'
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
        from onya.viz import nx
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


def test_legacy_serial_nx_alias_warns():
    '''`onya.serial.nx` still imports (lazy, so this needs no networkx) but warns.'''
    code = '''
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            import onya.serial.nx  # noqa: F401
        assert any(issubclass(w.category, DeprecationWarning) for w in caught), caught
        assert any('onya.viz.nx' in str(w.message) for w in caught), caught
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_legacy_serial_nx_alias_functionally_equivalent():
    '''With networkx actually available, the alias behaves identically to `onya.viz.nx`.'''
    pytest.importorskip('networkx')
    code = '''
        import warnings
        from onya.graph import graph
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            from onya.serial import nx as legacy_nx
        assert legacy_nx.to_networkx(graph()).number_of_nodes() == 0
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


def test_legacy_serial_mermaid_and_graphviz_aliases_warn():
    code = '''
        import warnings
        from io import StringIO
        from onya.graph import graph
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            from onya.serial import mermaid as legacy_mermaid
            from onya.serial import graphviz as legacy_graphviz
        assert sum(issubclass(w.category, DeprecationWarning) for w in caught) == 2, caught
        out = StringIO()
        legacy_mermaid.write(graph(), out=out)
        legacy_graphviz.write(graph(), out=out)
        print('OK')
    '''
    r = _run(code)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout
