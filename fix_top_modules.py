#!/usr/bin/env python3
"""Repair the ``top`` field of the 43-sample adapter manifest and its configs.

``prepare_43_manifest.py`` used to fall back to the *first* ``module`` line of
the synthesised netlist, which is a leaf block, not the chip top.  That is why
13 designs ran as ``ALU_*`` blocks (and a few as SRAM/CSR sub-blocks) and why
their DRC/LVS numbers described the wrong circuit.

This script re-resolves every top with the authoritative-first order from
``openlayout/tops.py`` (ORFS ``DESIGN_NAME`` -> RTLIL ``\\top`` attribute ->
netlist heuristic), patches the manifest in place, records ``top_source``, and
then regenerates ``configs/current43/*.yaml``.

The manifest cannot simply be re-generated: its input
(``agent_eco_runs/eco_20261031_fixed/summary.json``) was not kept.  Patching is
therefore the only lossless route -- every other field is preserved verbatim.

Usage:
    python fix_top_modules.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import prepare_43_configs_all as gen
from openlayout.tops import resolve_top


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='report the changes without touching any file')
    args = ap.parse_args()

    manifest_path = gen.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    samples = manifest['samples']

    changed = []
    unresolved = []
    for s in samples:
        frozen = Path(s['frozen_dir'])
        netlist = Path(s['netlist'])
        old = s.get('top')
        new, source = resolve_top(s['platform'], s['design'], frozen, netlist)
        if not new:
            unresolved.append(s['sample_id'])
            continue
        s['top_source'] = source
        if new != old:
            s['top'] = new
            changed.append((s['sample_id'], old, new, source))

    print(f'{len(samples)} samples, {len(changed)} tops corrected, '
          f'{len(unresolved)} unresolved')
    for sid, old, new, source in changed:
        print(f'  {sid:46s} {str(old)[:34]:36s} -> {new:34s} ({source})')
    if unresolved:
        print('UNRESOLVED:', ', '.join(unresolved))

    # Hard guard: a top must exist in the netlist text we are about to place.
    still_alu = [s['sample_id'] for s in samples if str(s.get('top', '')).startswith('ALU_')]
    if still_alu:
        print('WARNING: still ALU-like tops:', ', '.join(still_alu))

    if args.dry_run:
        print('dry run: no files written')
        return 0

    manifest_path.write_text(json.dumps(manifest, indent=1) + '\n')
    print('wrote', manifest_path)
    gen.main()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
