"""Resolve the RTL top module for a frozen net2GDS sample.

The 43-design adapter manifest used to guess the top from the first ``module``
line of the synthesised netlist, which is a leaf block (e.g.
``ALU_19_0_1_0_19_unused_CO_X_BRENT_KUNG``) rather than the chip top.  That
misidentified 13 designs and made every downstream DRC/LVS number describe a
different circuit.

Resolution order (authoritative first):
  1. ``DESIGN_NAME`` in the ORFS design config -- exactly what the reference
     OpenROAD flow elaborated;
  2. ``attribute \\top 1`` in the canonicalised RTLIL (yosys marks the top);
  3. heuristic on the netlist (explicit ``(* top = 1 *)`` else first module).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path('/data/taiyuzhou/net2GDS')


def top_from_netlist(path: Path) -> str | None:
    """Guess from the netlist text; only a last resort."""
    txt = path.read_text(errors='ignore')
    m = re.search(r'\(\*\s*top\s*=\s*1\s*\*\)\s*module\s+([A-Za-z_$][\w$]*)', txt)
    if m:
        return m.group(1)
    m = re.search(r'\bmodule\s+([A-Za-z_$][\w$]*)', txt)
    return m.group(1) if m else None


def top_from_orfs_config(platform: str, design: str) -> str | None:
    """``DESIGN_NAME`` from the ORFS design config."""
    p = ROOT / 'OpenROAD-flow-scripts/flow/designs' / platform / design / 'config.mk'
    if not p.exists():
        return None
    m = re.search(r'^\s*export\s+DESIGN_NAME\s*=\s*(\S+)',
                  p.read_text(errors='ignore'), re.M)
    return m.group(1) if m else None


def top_from_rtlil(frozen_dir: Path) -> str | None:
    """The canonicalised RTLIL carries ``attribute \\top 1`` on the real top."""
    p = Path(frozen_dir) / '1_1_yosys_canonicalize.rtlil'
    if not p.exists():
        return None
    marked = False
    with p.open(errors='ignore') as fh:
        for line in fh:
            s = line.strip()
            if s == 'attribute \\top 1':
                marked = True
                continue
            if marked and s.startswith('module '):
                return s[len('module '):].strip().lstrip('\\')
    return None


def resolve_top(platform: str, design: str, frozen_dir: Path,
                netlist: Path) -> tuple[str | None, str]:
    """Return ``(top, source)`` using the authoritative-first order above."""
    attempts = (
        ('orfs_config', lambda: top_from_orfs_config(platform, design)),
        ('rtlil_top_attribute', lambda: top_from_rtlil(frozen_dir)),
        ('netlist_heuristic',
         lambda: top_from_netlist(netlist) if Path(netlist).exists() else None),
    )
    for source, fn in attempts:
        try:
            value = fn()
        except Exception:
            value = None
        if value:
            return value, source
    return None, 'unresolved'
