"""Re-convert every OpenLayout final DEF to GDS with the current platform config.

The signoff pass only reads `gds/<design>.gds`; when a conversion fix lands
(LEF loading, gf180 9t layermap/GDS set) the existing GDS files are stale and
the DRC results describe the old conversion.  This re-runs only the DEF->GDS
step for all 43 samples, in parallel, and reports any remaining dummy macros.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, '/data/taiyuzhou/OpenLayout')
import run_43_batch as B  # noqa: E402

PY = '/data/taiyuzhou/.venv/bin/python'
OL = Path('/data/taiyuzhou/OpenLayout')


def convert(sample: dict) -> dict:
    sid = sample['sample_id']
    out = OL / 'output/current43' / sid
    final_def = out / 'saves_db' / (sample['design'] + '_final.def')
    if not final_def.exists():
        routed = out / 'saves_db' / 'route.routed.def'
        final_def = routed if routed.exists() else final_def
    if not final_def.exists():
        return {'sample_id': sid, 'status': 'no_def'}
    gds_dir = out / 'gds'
    gds_dir.mkdir(parents=True, exist_ok=True)
    gds = gds_dir / (sample['design'] + '.gds')
    plat = B.PLATFORM[sample['platform']]
    cmd = [PY, str(OL / 'convert_def_to_gds.py'), '--def', str(final_def),
           '--out', str(gds), '--tech-file', str(plat['tech']),
           '--design', sample['top']]
    if plat.get('map'):
        cmd += ['--layer-map', str(plat['map'])]
    for lef in B.platform_lefs(sample['platform'], sample):
        cmd += ['--lef', str(lef)]
    for g in B.platform_gds(sample['platform'], sample):
        cmd += ['--macro-gds', str(g)]
    log = gds_dir / (sample['design'] + '.gds.convert.stdout.log')
    with log.open('w') as fh:
        cp = subprocess.run(cmd, cwd=str(OL), stdout=fh, stderr=subprocess.STDOUT)
    try:
        info = json.loads(log.read_text().strip().splitlines()[-1]) if cp.returncode == 0 else {}
    except Exception:
        info = {}
    return {'sample_id': sid, 'status': 'ok' if cp.returncode == 0 else 'failed',
            'rc': cp.returncode, 'bytes': gds.stat().st_size if gds.exists() else 0,
            'dummy_macros': info.get('dummy_macros'), 'vias': info.get('invalid_vias'),
            'lefs': len(info.get('lefs') or [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--only-platform', action='append')
    args = ap.parse_args()
    samples = json.loads(B.MANIFEST.read_text())['samples']
    if args.only_platform:
        keep = set(args.only_platform)
        samples = [s for s in samples if s['platform'] in keep]

    bad = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for row in ex.map(convert, samples):
            flag = ''
            if row['status'] != 'ok' or (row.get('dummy_macros') or 0) > 0:
                bad += 1
                flag = '  <== PROBLEM'
            print(json.dumps(row, ensure_ascii=False) + flag, flush=True)
    print(f'\nconverted {len(samples)}, problems {bad}')
    return 0 if bad == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
