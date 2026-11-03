#!/usr/bin/env python3
"""Aggregate the per-design quality reports into the 43-design summary."""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path('/data/taiyuzhou')
OL = ROOT / 'OpenLayout'
manifest = json.loads((ROOT / 'net2GDS/reports/openlayout_43_manifest_20261102.json').read_text())['samples']
out_root = OL / 'output/current43'
rows = []
for s in manifest:
    d = out_root / s['sample_id']
    qpath = d / 'quality_report.json'
    q = json.loads(qpath.read_text()) if qpath.exists() else {}
    qual = q.get('quality', {})
    gds = next((p for p in (d / 'gds').glob('*.gds')), None) if (d / 'gds').exists() else None
    rows.append({
        'sample_id': s['sample_id'], 'platform': s['platform'], 'design': s['design'],
        'flow_completed': bool(q.get('flow_completed')), 'gds_generated': bool(q.get('gds_generated')) and bool(gds),
        'drc': qual.get('drc', 'missing'), 'drc_violations': qual.get('drc_violations'),
        'lvs': qual.get('lvs', 'not verified'), 'timing_closed': qual.get('timing_closed'),
        'timing_signoff_valid': qual.get('timing_signoff_valid', False),
        'signoff_accepted': bool((q.get('signoff') or {}).get('acceptance', False)),
        'wns_setup_ns': qual.get('wns_setup_ns'), 'wns_hold_ns': qual.get('wns_hold_ns'),
        'tns_ns': qual.get('tns_ns'), 'route_status': qual.get('route_status'),
        'finish_status': qual.get('finish_status'), 'gds': str(gds) if gds else None,
        'quality_report': str(qpath) if qpath.exists() else None,
        'llm_calls': json.loads((d / 'final_metrics.json').read_text()).get('usage', {}).get('llm_calls', 0) if (d / 'final_metrics.json').exists() else 0,
    })

def counts(items):
    return dict(Counter(items))

def status_count(mapping, *keys):
    """Read a status count while accepting the historical key spellings."""
    return sum(mapping.get(k, 0) for k in keys)

summary = {
    'total': len(rows),
    'flow_completed': sum(r['flow_completed'] for r in rows),
    'gds_generated': sum(r['gds_generated'] for r in rows),
    'drc': counts(r['drc'] for r in rows),
    'lvs': counts(r['lvs'] for r in rows),
    'timing_closed': counts(r['timing_closed'] for r in rows),
    'timing_signoff_valid': counts(r['timing_signoff_valid'] for r in rows),
    'signoff_accepted': counts(r['signoff_accepted'] for r in rows),
    'llm_calls_total': sum(r['llm_calls'] for r in rows),
    'llm_designs': sum(r['llm_calls'] > 0 for r in rows),
    'by_platform': {}, 'samples': rows,
}
for p in sorted(set(r['platform'] for r in rows)):
    subset = [r for r in rows if r['platform'] == p]
    summary['by_platform'][p] = {
        'total': len(subset), 'flow_completed': sum(r['flow_completed'] for r in subset),
        'gds_generated': sum(r['gds_generated'] for r in subset),
        'drc': counts(r['drc'] for r in subset), 'lvs': counts(r['lvs'] for r in subset),
        'timing_closed': counts(r['timing_closed'] for r in subset),
        'timing_signoff_valid': counts(r['timing_signoff_valid'] for r in subset),
        'signoff_accepted': counts(r['signoff_accepted'] for r in subset),
    }

json_path = ROOT / 'net2GDS/reports/openlayout_43_quality_summary_20261102.json'
json_path.write_text(json.dumps(summary, indent=2) + '\n')
md = ['# OpenLayout 43-design quality summary', '',
      f"- flow completed: **{summary['flow_completed']}/{summary['total']}**",
      f"- GDS generated: **{summary['gds_generated']}/{summary['total']}**", '',
      f"- DeepSeek LLM calls: **{summary['llm_calls_total']}** across {summary['llm_designs']}/{summary['total']} designs", '',
      '## Overall quality', '',
      f"- DRC: clean={summary['drc'].get('clean', 0)}, violations={summary['drc'].get('violations', 0)}, blocked={summary['drc'].get('blocked', 0)}",
      f"- LVS: match={status_count(summary['lvs'], 'match')}, mismatch={status_count(summary['lvs'], 'mismatch')}, not verified={status_count(summary['lvs'], 'not verified', 'not_verified')}, timeout={status_count(summary['lvs'], 'timeout')}, blocked={status_count(summary['lvs'], 'blocked')}",
      f"- timing closed: {summary['timing_closed'].get(True, 0)}/{summary['total']} ({100.0 * summary['timing_closed'].get(True, 0) / summary['total']:.1f}%)", '',
      f"- timing signoff-valid: {summary['timing_signoff_valid'].get(True, 0)}/{summary['total']}",
      f"- KLayout signoff accepted (DRC clean + LVS match): {summary['signoff_accepted'].get(True, 0)}/{summary['total']}", '',
      '## By platform', '', '| Platform | Flow/GDS | DRC clean | DRC violations | DRC blocked | Timing closed | LVS match | LVS mismatch | LVS not verified | LVS timeout |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for p, x in summary['by_platform'].items():
    md.append('| %s | %d/%d | %d | %d | %d | %d/%d | %d | %d | %d | %d |' %
              (p, x['flow_completed'], x['gds_generated'], x['drc'].get('clean', 0),
               x['drc'].get('violations', 0), x['drc'].get('blocked', 0),
               x['timing_closed'].get(True, 0), x['total'],
               status_count(x['lvs'], 'match'), status_count(x['lvs'], 'mismatch'),
               status_count(x['lvs'], 'not verified', 'not_verified'), status_count(x['lvs'], 'timeout')))
md += ['', '## Per-design reports', '', '| Sample | DRC | Timing | GDS | Quality report |', '|---|---|---|---|---|']
for r in rows:
    md.append('| %s | %s%s | %s | `%s` | `%s` |' %
              (r['sample_id'], r['drc'], '' if r['drc_violations'] is None else ' (%s)' % r['drc_violations'],
               r['timing_closed'], r['gds'], r['quality_report']))
(ROOT / 'net2GDS/reports/openlayout_43_quality_summary_20261102.md').write_text('\n'.join(md) + '\n')
print(json.dumps({k: summary[k] for k in ('total', 'flow_completed', 'gds_generated', 'drc', 'lvs', 'timing_closed')}, indent=2))
