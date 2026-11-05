#!/usr/bin/env python3
"""Run all 43 fixed samples, stream DEF to GDS, and write quality reports.

The runner is resumable.  A sample is skipped only when its quality report
marks the flow and GDS as complete; failed samples are retried on the next
invocation and retain their stage logs.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path('/data/taiyuzhou')
OL = ROOT / 'OpenLayout'
MANIFEST = ROOT / 'net2GDS/reports/openlayout_43_manifest_20261102.json'
PYTHON = ROOT / '.venv/bin/python'

PLATFORM = {
    'nangate45': {
        'tech': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/nangate45/FreePDK45.lyt',
        'gds': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/nangate45/gds/NangateOpenCellLibrary.gds'],
        'lefs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef',
                 ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.macro.mod.lef'],
    },
    'gf180': {
        'tech': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/KLayout/gf180mcu_5LM_1TM_9K_9t.lyt',
        'gds_dirs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/gds/7t', ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/gds/9t'],
        'map': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/gds/7t/gf180mcu_5LM_1TM_9K_7t_edi2gds.layermap',
        'lefs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/lef/gf180mcu_5LM_1TM_9K_9t_tech.lef',
                 ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/gf180/lef/gf180mcu_5LM_1TM_9K_9t_sc.lef'],
    },
    'ihp-sg13g2': {
        # The stock sg13g2.lyt references a relative map file that KLayout
        # resolves against the DEF directory in this container.  Use the
        # generic LEF/DEF reader technology for artifact generation; the
        # OpenROAD route/quality metrics still come from the IHP run.
        'tech': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/nangate45/FreePDK45.lyt',
        'gds_dir': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/ihp-sg13g2/gds',
        'map': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/ihp-sg13g2/sg13g2.map',
        'lefs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/ihp-sg13g2/lef/sg13g2_tech.lef',
                 ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/ihp-sg13g2/lef/sg13g2_stdcell.lef'],
    },
    'sky130hd': {
        'tech': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hd/sky130hd.lyt',
        'gds': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hd/gds/sky130_fd_sc_hd.gds'],
        'lefs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hd/lef/sky130_fd_sc_hd.tlef',
                 ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hd/lef/sky130_fd_sc_hd_merged.lef'],
    },
    'sky130hs': {
        'tech': ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hs/sky130hs.lyt',
        'gds': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hs/gds/sky130_fd_sc_hs.gds'],
        'lefs': [ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hs/lef/sky130_fd_sc_hs.tlef',
                 ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/platforms/sky130hs/lef/sky130_fd_sc_hs_merged.lef'],
    },
}

def platform_gds(platform, sample=None):
    p = PLATFORM[platform]
    if 'gds' in p:
        return p['gds']
    if 'gds_dirs' in p:
        return sorted(g for d in p['gds_dirs'] for g in d.glob('*.gds'))
    out = sorted(p['gds_dir'].glob('*.gds'))
    if sample and sample['platform'] == 'sky130hd' and sample['design'] == 'chameleon':
        out += sorted((ROOT / 'net2GDS/OpenROAD-flow-scripts/flow/designs/sky130hd/chameleon/gds').glob('*.gds*'))
    return out

def read_manifest():
    return json.loads(MANIFEST.read_text())['samples']

def run_one(sample, force=False, skip_flow=False):
    sid = sample['sample_id']
    out = OL / 'output/current43' / sid
    q = out / 'quality_report.json'
    if not force and q.exists():
        try:
            old = json.loads(q.read_text())
            if old.get('flow_completed') and old.get('gds_generated'):
                return {'sample_id': sid, 'status': 'skipped', 'quality': old.get('quality', {})}
        except Exception:
            pass
    out.mkdir(parents=True, exist_ok=True)
    batch_log = OL / 'output/current43/_batch_logs' / (sid + '.stdout.log')
    batch_log.parent.mkdir(parents=True, exist_ok=True)
    cfg = OL / 'configs/current43' / (sid + '.yaml')
    start = time.time()
    final_def = out / 'saves_db' / (sample['design'] + '_final.def')
    have_flow = (out / 'saves_db' / '05_finish.odb').exists() and final_def.exists()
    if skip_flow and have_flow:
        result = {'sample_id': sid, 'platform': sample['platform'], 'design': sample['design'],
                  'flow_rc': 0, 'flow_seconds': 0.0, 'log': str(batch_log),
                  'flow_skipped': True}
    else:
        cmd = [str(PYTHON), str(OL / 'run_openlayout.py'), '--config', str(cfg), '--stages', 'all']
        with batch_log.open('w') as log:
            log.write('$ ' + ' '.join(cmd) + '\n')
            log.flush()
            proc = subprocess.run(cmd, cwd=str(OL), stdout=log, stderr=subprocess.STDOUT,
                                  env=os.environ.copy(), timeout=12 * 3600)
        result = {'sample_id': sid, 'platform': sample['platform'], 'design': sample['design'],
                  'flow_rc': proc.returncode, 'flow_seconds': round(time.time() - start, 1),
                  'log': str(batch_log)}
    if not final_def.exists():
        routed = out / 'saves_db' / 'route.routed.def'
        if routed.exists():
            final_def = routed
    if not final_def.exists():
        result['status'] = 'flow_failed_no_def'
        (out / 'batch_result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    gds_dir = out / 'gds'
    gds_file = gds_dir / (sample['design'] + '.gds')
    conv = [str(PYTHON), str(OL / 'convert_def_to_gds.py'), '--def', str(final_def),
            '--out', str(gds_file), '--tech-file', str(PLATFORM[sample['platform']]['tech']),
            '--design', sample['top']]
    for lef in PLATFORM[sample['platform']].get('lefs', []):
        conv += ['--lef', str(lef)]
    if PLATFORM[sample['platform']].get('map'):
        conv += ['--layer-map', str(PLATFORM[sample['platform']]['map'])]
    for g in platform_gds(sample['platform'], sample):
        conv += ['--macro-gds', str(g)]
    conv_log = gds_dir / (sample['design'] + '.gds.convert.stdout.log')
    gds_dir.mkdir(parents=True, exist_ok=True)
    with conv_log.open('w') as log:
        cp = subprocess.run(conv, cwd=str(OL), stdout=log, stderr=subprocess.STDOUT,
                            env=os.environ.copy(), timeout=3600)
    result['convert_rc'] = cp.returncode
    if cp.returncode != 0 or not gds_file.exists() or gds_file.stat().st_size == 0:
        result['status'] = 'gds_failed'
        (out / 'batch_result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    qr = [str(PYTHON), str(OL / 'write_quality_report.py'), '--output-dir', str(out),
          '--gds', str(gds_file), '--lvs', 'not verified']
    qp = subprocess.run(qr, cwd=str(OL), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        env=os.environ.copy(), timeout=120, text=True)
    result['quality_rc'] = qp.returncode
    result['quality_report'] = str(out / 'quality_report.json')
    try:
        result['quality'] = json.loads((out / 'quality_report.json').read_text()).get('quality', {})
    except Exception:
        result['quality'] = {}
    result['status'] = 'complete' if qp.returncode == 0 else 'quality_failed'
    (out / 'batch_result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--only-platform', action='append')
    ap.add_argument('--only-sample', action='append')
    ap.add_argument('--skip-flow', action='store_true', help='convert/report existing finish artifacts only')
    ap.add_argument('--signoff', action='store_true',
                    help='run the KLayout DRC/LVS adapter after the flow and update quality reports')
    args = ap.parse_args()
    samples = read_manifest()
    if args.only_platform:
        samples = [s for s in samples if s['platform'] in args.only_platform]
    if args.only_sample:
        wanted = set(args.only_sample)
        samples = [s for s in samples if s['sample_id'] in wanted]
    state_path = OL / 'output/current43/batch_state.json'
    state = {'started': time.strftime('%F %T'), 'total': len(samples), 'results': {}}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {ex.submit(run_one, s, args.force, args.skip_flow): s['sample_id'] for s in samples}
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {'sample_id': sid, 'status': 'runner_exception', 'error': repr(exc)}
            state['results'][sid] = r
            state['finished'] = time.strftime('%F %T')
            state_path.write_text(json.dumps(state, indent=2) + '\n')
            print(json.dumps(r, ensure_ascii=False), flush=True)
    state['completed'] = time.strftime('%F %T')
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    counts = {}
    for r in state['results'].values():
        counts[r.get('status')] = counts.get(r.get('status'), 0) + 1
    if args.signoff and counts.get('complete', 0) == len(samples):
        signoff_cmd = [str(PYTHON), str(OL / 'run_klayout_signoff_43.py'),
                       '--workers', str(max(1, args.workers))]
        if args.force:
            signoff_cmd.append('--force')
        for platform in (args.only_platform or []):
            signoff_cmd += ['--only-platform', platform]
        for sample in (args.only_sample or []):
            signoff_cmd += ['--only-sample', sample]
        print('$ ' + ' '.join(signoff_cmd), flush=True)
        signoff = subprocess.run(signoff_cmd, cwd=str(OL),
                                 env=os.environ.copy())
        counts['signoff_rc'] = signoff.returncode
    print(json.dumps({'counts': counts, 'state': str(state_path)}, ensure_ascii=False), flush=True)
    return 0 if counts.get('complete', 0) == len(samples) and counts.get('signoff_rc', 0) == 0 else 2

if __name__ == '__main__':
    raise SystemExit(main())
