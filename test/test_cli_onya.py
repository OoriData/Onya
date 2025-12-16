# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2023-present Oori Data <info@oori.dev>
# SPDX-License-Identifier: Apache-2.0
# test_cli_onya.py
'''
Smoke tests for the `onya` CLI surface.

These tests call the underlying functions directly (rather than shelling out),
so they don't depend on console-script wiring.
'''

from pathlib import Path

from onya.cli.onya import convert


def test_cli_convert_mermaid(tmp_path: Path):
    src = Path(__file__).resolve().parent / 'resource' / 'schemaorg' / 'thingsfallapart.onya'
    out = tmp_path / 'out.mmd'

    convert(str(src), mermaid=True, out=str(out))

    mmd = out.read_text(encoding='utf-8')
    assert 'flowchart' in mmd


def test_cli_convert_dot(tmp_path: Path):
    src = Path(__file__).resolve().parent / 'resource' / 'schemaorg' / 'thingsfallapart.onya'
    out = tmp_path / 'out.dot'

    convert(str(src), dot=True, out=str(out))

    dot = out.read_text(encoding='utf-8')
    assert 'digraph G {' in dot

