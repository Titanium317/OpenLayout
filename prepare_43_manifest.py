#!/usr/bin/env python3
"""Build the fixed 43-sample OpenLayout adapter manifest.

The manifest is intentionally generated from the already selected ECO sample
list, rather than enumerating every task directory (which includes replays and
patch variants). It records the frozen netlist/SDC and the platform adapter
status used by the batch runner.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from collections import Counter

ROOT = Path('/data/taiyuzhou/net2GDS')
TASKS = ROOT / 'final_test_dataset/tasks'
SUMMARY = ROOT / 'agent_eco_runs/eco_20261031_fixed/summary.json'
OUT = ROOT / 'reports/openlayout_43_manifest_20261102.json'

platform_status = {
    'nangate45': 'adapter_bp_fe_validated_route_blocked',
    'ihp-sg13g2': 'adapter_pending_platform_layers',
    'sky130hd': 'adapter_pending_platform_layers',
    'gf180': 'adapter_pending_platform_layers',
    'sky130hs': 'adapter_pending_platform_layers',
}

def top_from_netlist(path: Path) -> str | None:
    txt = path.read_text(errors='ignore')
    m = re.search(r'\(\*\s*top\s*=\s*1\s*\*\)\s*module\s+([A-Za-z_$][\w$]*)', txt)
    if m:
        return m.group(1)
    m = re.search(r'\bmodule\s+([A-Za-z_$][\w$]*)', txt)
    return m.group(1) if m else None

selected = json.loads(SUMMARY.read_text())['samples']
rows=[]
for x in selected:
    platform, design, variant = x['sample_id'].split('__', 2)
    task_dir = next(TASKS.glob(x['parent_task_id'] + '/task.json'))
    task = json.loads(task_dir.read_text())
    frozen = Path(task['frozen_dir'])
    netlist = frozen / 'netlist.v'
    sdc = frozen / 'constraint_post_synth.sdc'
    rows.append({
        'sample_id': x['sample_id'],
        'platform': platform,
        'design': design,
        'variant': variant,
        'parent_task_id': x['parent_task_id'],
        'task_dir': str(task_dir.parent),
        'frozen_dir': str(frozen),
        'netlist': str(netlist),
        'sdc': str(sdc),
        'top': top_from_netlist(netlist) if netlist.exists() else None,
        'netlist_exists': netlist.exists(),
        'sdc_exists': sdc.exists(),
        'platform_adapter': platform_status.get(platform, 'unsupported'),
        'baseline': {
            'drc_violations': x.get('klayout_drc_violations'),
            'lvs': x.get('lvs'),
            'wns_ns': x.get('wns_ns'),
            'gds_exists': bool(x.get('baseline', {}).get('final_drc_violations') is not None),
        },
    })
OUT.write_text(json.dumps({
    'generated': '2026-11-02',
    'source_run': 'eco_20261031_fixed',
    'count': len(rows),
    'platform_counts': dict(Counter(r['platform'] for r in rows)),
    'platform_status': platform_status,
    'samples': rows,
}, indent=2, ensure_ascii=False) + '\n')
print(OUT)
print('count=', len(rows))
print('platform_counts=', dict(Counter(r['platform'] for r in rows)))
